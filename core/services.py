from django.core.exceptions import ValidationError
from django.db import transaction
from django.db import models

from .models import SolicitacaoEvento, TransacaoEstoque, TipoTransacao, Item

def alocar_item_para_evento(id_item, quantidade_a_alocar, id_evento ,responsavel):
    if quantidade_a_alocar <= 0:
        raise ValidationError({'quantidade': 'A Quantidade deve ser positva'})

    with transaction.atomic():
        solicitacao = SolicitacaoEvento.objects.select_for_update().get(evento_id=id_evento, item_id=id_item)

        TransacaoEstoque.objects.create(
            item_id=id_item,
            tipo=TipoTransacao.ALOCACAO_EVENTO,
            quantidade=quantidade_a_alocar,
            evento_id=id_evento,
            responsavel=responsavel,
        )

        solicitacao.quantidade_alocada = models.F('quantidade_alocada') + quantidade_a_alocar
        solicitacao.save()


def retornar_item_de_evento(id_item, quantidade_a_retornar, id_evento, responsavel):
    saldos_por_preco = TransacaoEstoque.objects.filter(
        evento_id=id_evento,
        item_id=id_item,
        tipo__in=(TipoTransacao.ALOCACAO_EVENTO, TipoTransacao.RETORNO_EVENTO)
    ).values(
        'preco_unidade'
    ).annotate(
        saldo_liquido=models.Sum(
            models.Case(
                models.When(tipo=TipoTransacao.RETORNO_EVENTO, then=-models.F('quantidade')),
                default=models.F('quantidade'),
                output_field=models.PositiveIntegerField()
            )
        ),
        primeira_alocacao=models.Min(
            'timestamp',
            filter=models.Q(tipo=TipoTransacao.ALOCACAO_EVENTO)
        )
    ).filter(
        saldo_liquido__gt=0
    ).order_by(
        'primeira_alocacao'
    ).values_list('saldo_liquido', 'preco_unidade')

    if quantidade_a_retornar > (quantidade_disponivel_retorno := saldos_por_preco.aggregate(
                                                                     quantidade_disponivel_retorno=models.Sum(
                                                                         'saldo_liquido'
                                                                     )
                                                                 )['quantidade_disponivel_retorno']):
        raise ValidationError({
            'quantidade_a_retornar': 'Não é possível retornar mais itens do que foram alocados. '
                                     f'Quantidade disponível para retorno {quantidade_disponivel_retorno}'
        })

    with transaction.atomic():
        try:
            item = Item.objects.select_for_update().get(id=id_item)
        except Item.DoesNotExist:
            raise ValidationError({'id_item': 'O id_item informado não corresponse a nenhum item no sistema'})

        for saldo_liquido, preco_unidade in saldos_por_preco:
            if quantidade_a_retornar <= 0:
                break

            TransacaoEstoque.objects.create(
                item=item,
                tipo=TipoTransacao.RETORNO_EVENTO,
                evento_id=id_evento,
                quantidade=min(saldo_liquido, quantidade_a_retornar),
                preco_unidade=preco_unidade,
                responsavel=responsavel
            )

            quantidade_a_retornar -= saldo_liquido
