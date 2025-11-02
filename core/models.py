from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction


class TipoTransacao(models.TextChoices):
    COMPRA = 'compra', 'Compra'
    ALOCACAO_EVENTO = 'alocacao', 'Alocação para Evento'
    RETORNO_EVENTO = 'retorno', 'Retorno de Evento'
    REMOCAO_MANUAL = 'remocao', 'Remoção Manual'
    ADICAO_MANUAL = 'adicao', 'Adição Manual'
    PATROCINIO = 'patrocinio', 'Patrocínio'
    CONSUMO_INTERNO = 'consumo', 'Consumo Interno'


class StatusEvento(models.TextChoices):
    EM_ANDAMENTO = 'andamento', 'Em Andamento'
    CONCLUIDO = 'concluido', 'Concluído'


EXPR_QUANTIDADE_LIQUIDA = models.Sum(
    models.Case(
        models.When(tipo=TipoTransacao.RETORNO_EVENTO, then=-models.F('quantidade')),
        default=models.F('quantidade'),
        output_field=models.PositiveIntegerField()
    )
)

EXPR_CUSTO_LIQUIDO = models.Sum(
    models.Case(
        models.When(tipo=TipoTransacao.RETORNO_EVENTO, then=-models.F('valor_total')),
        default=models.F('valor_total'),
        output_field=models.DecimalField(max_digits=10, decimal_places=4)
    )
)


class Item(models.Model):
    class Meta:
        verbose_name_plural = 'Itens'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantidade_em_estoque__gte=0),
                name='quantidade_em_estoque_gte_zero'
            ),
            models.CheckConstraint(
                condition=models.Q(valor_total__gte=0),
                name='valor_total_gte_zero'
            )
        ]

    nome = models.CharField(max_length=100)
    quantidade_em_estoque = models.IntegerField(default=0, editable=False)
    valor_total = models.DecimalField(max_digits=10, decimal_places=4, default=0, editable=False)
    preco_medio = models.GeneratedField(
        expression=models.Case(
            models.When(quantidade_em_estoque=0, then=models.Value('0.00')),
            default=models.F('valor_total') / models.F('quantidade_em_estoque'),
            output_field=models.DecimalField(max_digits=10, decimal_places=4)
        ),
        output_field=models.DecimalField(max_digits=10, decimal_places=4),
        db_persist=False
    )

    def __str__(self):
        return self.nome


class TransacaoEstoqueQuerySet(models.QuerySet):
    def ultimo_preco_unidade_pago(self, id_item):
        return self.filter(
            item_id=id_item,
            tipo=TipoTransacao.COMPRA
        ).order_by(
            '-timestamp'
        ).values(
            'preco_unidade',
        )[:1]

    def get_itens_consumidos_com_preco(self):
        return self.order_by(
        ).filter(
            preco_unidade__gt=0
        ).values(
            'item',
            'preco_unidade'
        ).annotate(
            quantidade_consumida=EXPR_QUANTIDADE_LIQUIDA
        ).filter(
            quantidade_consumida__gt=0
        ).values_list(
            'quantidade_consumida',
            'item__nome',
            'preco_unidade'
        )


class TransacaoEstoque(models.Model):
    class Meta:
        verbose_name = 'Transação de Estoque'
        verbose_name_plural = 'Transações de Estoque'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantidade__gt=0),
                name='quantidade_maior_que_zero'
            ),
            models.CheckConstraint(
                condition=models.Q(preco_unidade__gte=0),
                name='preco_positivo'
            )
        ]

    Tipo = TipoTransacao
    objects = TransacaoEstoqueQuerySet.as_manager()
    item = models.ForeignKey(Item, on_delete=models.PROTECT, db_index=True)
    tipo = models.CharField(choices=TipoTransacao.choices, db_index=True, max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    quantidade = models.IntegerField(validators=[MinValueValidator(1)])
    preco_unidade = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        blank=True,
        validators=(MinValueValidator(0),),
        verbose_name='Preço Unidade'
    )
    evento = models.ForeignKey(
        'core.Evento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name='transacoes',
        limit_choices_to={'status': StatusEvento.EM_ANDAMENTO}
    )
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, editable=False, null=True)
    nota = models.TextField(null=True, blank=True)
    valor_total = models.GeneratedField(
        expression=models.F('quantidade') * models.F('preco_unidade'),
        output_field=models.DecimalField(max_digits=10, decimal_places=4),
        db_persist=False
    )

    def clean(self):
        super().clean()

        if self.tipo in (TipoTransacao.ALOCACAO_EVENTO, TipoTransacao.RETORNO_EVENTO):
            if self.tipo == TipoTransacao.RETORNO_EVENTO:
                quantidade_maxima_retorno = TransacaoEstoque.objects.filter(
                    evento=self.evento,
                    item=self.item
                ).aggregate(
                    quantidade_maxima_retorno=EXPR_QUANTIDADE_LIQUIDA
                )['quantidade_maxima_retorno']

                if quantidade_maxima_retorno is None:
                    raise ValidationError({
                        'item': 'Este item não foi alocado para o evento. Não é possível realizar um retorno'
                    })
                if self.quantidade > quantidade_maxima_retorno:
                    raise ValidationError({
                        'quantidade': 'Quantidade de retornos maior do que itens alocados. '
                                      f'Disponível para retorno: {quantidade_maxima_retorno}'
                    })
            if not self.evento:
                raise ValidationError({'evento': 'É necessário associar um evento para transações alocação e retorno'})
        elif self.evento:
            raise ValidationError({'evento': 'Só é possível associar transações de alocação e retorno a um evento'})

        if self.tipo in (TipoTransacao.ADICAO_MANUAL, TipoTransacao.COMPRA) and not self.preco_unidade:
            raise ValidationError({'preco_unidade': 'É necessário informar um valor para compras e adições manuais'})

        if self.tipo in (TipoTransacao.ALOCACAO_EVENTO, TipoTransacao.REMOCAO_MANUAL, TipoTransacao.CONSUMO_INTERNO):
            if self.item.quantidade_em_estoque < self.quantidade:
                raise ValidationError({
                    'quantidade': f'Estoque insuficiente. Disponível: {self.item.quantidade_em_estoque}'
                })

    def save(self, **kwargs):
        if self.pk is not None:
            super().save(**kwargs)
            return

        with transaction.atomic():
            item_para_atualizar = Item.objects.select_for_update().get(pk=self.item.pk)

            match self.tipo:
                case TipoTransacao.COMPRA | TipoTransacao.ADICAO_MANUAL | TipoTransacao.PATROCINIO | TipoTransacao.RETORNO_EVENTO:
                    if self.tipo == TipoTransacao.PATROCINIO:
                        self.preco_unidade = 0

                    valor_transacao = self.quantidade * self.preco_unidade

                    item_para_atualizar.quantidade_em_estoque = models.F('quantidade_em_estoque') + self.quantidade
                    item_para_atualizar.valor_total = models.F('valor_total') + valor_transacao
                case TipoTransacao.ALOCACAO_EVENTO | TipoTransacao.REMOCAO_MANUAL | TipoTransacao.CONSUMO_INTERNO:
                    if not self.tipo == TipoTransacao.REMOCAO_MANUAL or not self.preco_unidade:
                        self.preco_unidade = item_para_atualizar.preco_medio
                    item_para_atualizar.quantidade_em_estoque -= self.quantidade
                    item_para_atualizar.valor_total -= self.quantidade * self.preco_unidade

            item_para_atualizar.save(update_fields=['quantidade_em_estoque', 'valor_total'])
            super().save(**kwargs)

    def __str__(self):
        return f'{self.get_tipo_display()} de {self.quantidade} {self.item}(s)'


class EventoQuerySet(models.QuerySet):
    def com_custo_total(self):
        return self.annotate(
            custo_total_calculado=models.Subquery(
                TransacaoEstoque.objects.filter(
                    evento_id=models.OuterRef('id')
                ).values(
                    'evento_id'
                ).annotate(
                    custo_total=EXPR_CUSTO_LIQUIDO
                ).values(
                    'custo_total'
                )
            )
        )


class Evento(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['nome', 'data'], name='unique_evento_em_data')
        ]
    Status = StatusEvento

    objects = EventoQuerySet.as_manager()
    nome = models.CharField(max_length=100)
    data = models.DateField()
    status = models.CharField(max_length=20, choices=StatusEvento.choices, default=StatusEvento.EM_ANDAMENTO)

    @property
    def custo_total(self):
        if hasattr(self, 'custo_total_calculado'):
            return self.custo_total_calculado

        custo_total = self.transacoes.aggregate(
            custo_total=EXPR_CUSTO_LIQUIDO
        )['custo_total']

        return custo_total

    def __str__(self):
        return f'{self.nome} {self.data.strftime('%d/%m/%Y')}'


class SolicitacaoEventoQuerySet(models.QuerySet):
    def com_sumario_de_itens(self, id_evento):
        transacoes_subquery = TransacaoEstoque.objects.filter(
            evento_id=id_evento,
            item_id=models.OuterRef('item_id')
        ).values('item_id')

        return self.filter(
            evento_id=id_evento
        ).annotate(
            quantidade_consumida = models.Subquery(
                transacoes_subquery.annotate(
                    quantidade_consumida=EXPR_QUANTIDADE_LIQUIDA
                ).values(
                    'quantidade_consumida'
                )
            ),
            custo = models.Subquery(
                transacoes_subquery.annotate(
                    custo=EXPR_CUSTO_LIQUIDO
                ).values(
                    'custo'
                )
            )
        )


class SolicitacaoEvento(models.Model):
    class Meta:
        verbose_name = 'Solicitação Evento'
        verbose_name_plural = 'Solicitações de Eventos'
        constraints = [
            models.UniqueConstraint(fields=['evento', 'item'], name='unique_solitacao_item_evento'),
            models.CheckConstraint(
                condition=models.Q(quantidade_solicitada__gt=0),
                name='quantidade_solicitada_maior_que_zero'
            ),
            models.CheckConstraint(
                condition=models.Q(quantidade_alocada__gte=0),
                name='quantidade_alocada_maior_ou_igual_zero'
            ),
            models.CheckConstraint(
                condition=models.Q(quantidade_alocada__lte=models.F('quantidade_solicitada')),
                    name='quantidade_alocada_nao_deve_exceder_solicitada'
            )
        ]

    objects = SolicitacaoEventoQuerySet.as_manager()
    evento = models.ForeignKey(
        Evento,
        on_delete=models.CASCADE,
        related_name='solicitacoes',
        limit_choices_to={'status': StatusEvento.EM_ANDAMENTO}
    )
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantidade_solicitada = models.IntegerField(validators=[MinValueValidator(1)])
    quantidade_alocada = models.IntegerField(default=0, editable=False)
    quantidade_faltando = models.GeneratedField(
        expression=models.F('quantidade_solicitada') - models.F('quantidade_alocada'),
        db_persist=False,
        output_field=models.PositiveIntegerField()
    )

    def clean(self):
        if self.quantidade_solicitada and self.quantidade_solicitada < self.quantidade_alocada:
            raise ValidationError(
                {
                    'quantidade_solicitada': f'Já foram alocados {self.quantidade_alocada} itens. Não é possível mudar '
                                              'a quantidade solicitada para menos que isso'
                }
            )

    def __str__(self):
        return f'{self.quantidade_solicitada} {self.item.nome}(s) para {self.evento}'
