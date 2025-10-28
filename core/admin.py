from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import HttpResponse

from rangefilter.filters import DateTimeRangeFilter, DateRangeFilter

from .planilhas import gerar_checklist, gerar_lista_compras, gerar_custo_evento
from .models import Evento, TransacaoEstoque, SolicitacaoEvento, Item, TipoTransacao
from . import services
from .forms import TransacaoEstoqueAdminForm

admin.site.disable_action('delete_selected')
admin.site.site_header = 'Ju Miranda Produções'
admin.site.site_title = 'Administração de Camarins'
admin.site.index_title = 'Administração de Camarins'
admin.site.site_url = None

def obter_id_evento_unico(queryset):
    lista_eventos = queryset.order_by().values_list('evento_id', flat=True).distinct()

    if lista_eventos.count() != 1:
        raise ValidationError('Por favor, selecione solicitações de somente um evento')

    return lista_eventos.first()


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    search_fields = ('nome',)
    list_display = ('nome', 'data', 'custo_total')
    date_hierarchy = 'data'
    list_filter = ['status', ('data', DateRangeFilter)]

    def change_view(self, request, object_id, form_url='', extra_context=None):
        transacoes_subquery = TransacaoEstoque.objects.filter(
            evento_id=object_id,
            item_id=models.OuterRef('item_id')
        )

        sumario_itens_evento = SolicitacaoEvento.objects.filter(
            evento_id=object_id
        ).annotate(
            quantidade_consumida=models.Subquery(
                transacoes_subquery.annotate(
                    quantidade_consumida=models.Sum(
                        models.Case(
                            models.When(tipo=TipoTransacao.RETORNO_EVENTO, then=-models.F('quantidade')),
                            default=models.F('quantidade'),
                            output_field=models.PositiveIntegerField()
                        )
                    )
                ).values(
                    'quantidade_consumida'
                )
            ),
            custo=models.Subquery(
                transacoes_subquery.annotate(
                    custo=models.Sum(
                        models.Case(
                            models.When(tipo=TipoTransacao.RETORNO_EVENTO, then=-models.F('valor_total')),
                            default=models.F('valor_total'),
                            output_field=models.DecimalField(max_digits=10, decimal_places=2)
                        )
                    )
                ).values(
                    'custo'
                )
            )
        ).values_list(
            'item__nome',
            'quantidade_solicitada',
            'quantidade_alocada',
            'quantidade_consumida',
            'custo',
            named=True
        )

        return super().change_view(
            request, object_id, form_url, extra_context={'sumario_itens_evento': sumario_itens_evento},
        )

    def has_delete_permission(self, request, obj=None):
        if obj and obj.itens_solicitados.filter(quantidade_alocada__gt=0):
            return False

        return True

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        return qs.com_custo_total()

    def get_exclude(self, request, obj=None):
        if obj is None:
            return ('status',)

        return ()


class EventosEmAndamentoFilter(admin.SimpleListFilter):
    title = 'Eventos em Andamento'

    parameter_name = 'evento'

    def lookups(self, request, model_admin):
        eventos_em_andamento = Evento.objects.filter(status=Evento.Status.EM_ANDAMENTO)
        return [(evento.id, evento.__str__()) for evento in eventos_em_andamento]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(evento__id=self.value())

        return queryset


@admin.register(TransacaoEstoque)
class TransacaoEstoqueAdmin(admin.ModelAdmin):
    class Media:
        js = ('admin/js/confirmacao_criacao.js',)

    form = TransacaoEstoqueAdminForm
    autocomplete_fields = ('evento', 'item')
    search_fields = ('evento__nome', 'item__nome')
    list_display = ('tipo', 'evento', 'item', 'quantidade', 'preco_unidade', 'valor_total')
    list_filter = ('tipo', EventosEmAndamentoFilter, ('timestamp', DateTimeRangeFilter))
    date_hierarchy = 'timestamp'
    actions = ('baixar_planilha_custo_evento',)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            if obj.evento:
                return 'tipo', 'evento', 'item', 'quantidade', 'preco_unidade', 'responsavel'
            return 'tipo', 'item', 'quantidade', 'preco_unidade', 'responsavel'

        return ()

    def get_exclude(self, request, obj=None):
        if obj is not None and not obj.evento:
            return ('evento',)
        return ()

    def save_model(self, request, obj, form, change):
        if not change:
            obj.responsavel = request.user
            match obj.tipo:
                case TipoTransacao.ALOCACAO_EVENTO:
                    services.alocar_item_para_evento(obj.item.id, obj.quantidade, obj.evento.id, obj.responsavel)
                    return
                case TipoTransacao.RETORNO_EVENTO:
                    services.retornar_item_de_evento(obj.item.id, obj.quantidade, obj.evento.id, obj.responsavel)
                    return
        super().save_model(request, obj, form, change)

    @admin.action(description='Gerar planilha de custos do evento')
    def baixar_planilha_custo_evento(self, request, queryset):
        try:
            id_evento = obter_id_evento_unico(queryset)
        except ValidationError as e:
            self.message_user(request, e.message, messages.ERROR)
            return

        evento = Evento.objects.get(id=id_evento)
        titulo = evento.__str__()

        lista_itens = queryset.order_by(
        ).filter(
            preco_unidade__gt=0
        ).values(
            'item',
            'preco_unidade'
        ).annotate(
            quantidade_consumida=models.Sum(
                models.Case(
                    models.When(tipo=TipoTransacao.RETORNO_EVENTO, then=-models.F('quantidade')),
                    default=models.F('quantidade'),
                    output_field=models.PositiveIntegerField()
                )
            )
        ).filter(
            quantidade_consumida__gt=0
        ).values_list('quantidade_consumida', 'item__nome', 'preco_unidade')

        planilha_custo_evento = gerar_custo_evento(lista_itens, titulo)

        return HttpResponse(
            planilha_custo_evento,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': f'attachment; filename=custo_evento_{titulo.replace(' ', '_')}.xlsx'
            }
        )


@admin.register(SolicitacaoEvento)
class SolicitacaoEventoAdmin(admin.ModelAdmin):
    autocomplete_fields = ('evento', 'item')
    list_display = ('evento', 'item', 'quantidade_solicitada' ,'quantidade_alocada')
    list_filter = (EventosEmAndamentoFilter,)
    actions = ('baixar_checklist_producao', 'alocar_estoque', 'baixar_lista_compras')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.filter(evento__status=Evento.Status.EM_ANDAMENTO)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.quantidade_alocada > 0:
            return False

        return True

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return ('quantidade_alocada',)

        return ()

    @admin.action(description='Gerar checklist produção')
    def baixar_checklist_producao(self, request, queryset):
        try:
            id_evento = obter_id_evento_unico(queryset)
        except ValidationError as e:
            self.message_user(request, e.message, messages.ERROR)
            return

        evento = Evento.objects.get(id=id_evento)
        titulo = evento.__str__()

        lista_itens = queryset.filter(
            quantidade_alocada__gt=0
        ).values_list(
            'quantidade_alocada',
            'item__nome'
        )

        planilha = gerar_checklist(lista_itens, titulo)
        return HttpResponse(
            planilha,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename=checklist_{titulo.replace(' ', '_')}.xlsx'}
        )

    @admin.action(description='Alocar quantidade disponível no estoque')
    def alocar_estoque(self, request, queryset):
        try:
            id_evento = obter_id_evento_unico(queryset)
        except ValidationError as e:
            self.message_user(request, e.message, messages.ERROR)
            return

        solicitacoes = queryset
        transacoes_para_criar = []
        solicitacoes_para_atualizar = []
        itens_para_atualizar = []

        ids_itens_para_travar = {s.item_id for s in solicitacoes}

        with transaction.atomic():
            items_map = {
                item.id: item for item in
                Item.objects.select_for_update().filter(id__in=ids_itens_para_travar)
            }

            for solicitacao in solicitacoes:
                item = items_map[solicitacao.item.id]

                quantidade_a_alocar = min(item.quantidade_em_estoque, solicitacao.quantidade_faltando)

                if quantidade_a_alocar <= 0:
                    continue

                item.quantidade_em_estoque -= quantidade_a_alocar
                item.valor_total -= quantidade_a_alocar * item.preco_medio

                itens_para_atualizar.append(item)

                transacoes_para_criar.append(
                    TransacaoEstoque(
                        tipo=TipoTransacao.ALOCACAO_EVENTO,
                        evento_id=id_evento,
                        item=item,
                        quantidade=quantidade_a_alocar,
                        responsavel=request.user,
                        preco_unidade=item.preco_medio
                    )
                )

                solicitacao.quantidade_alocada += quantidade_a_alocar
                solicitacoes_para_atualizar.append(solicitacao)

            if itens_para_atualizar:
                Item.objects.bulk_update(
                    itens_para_atualizar,
                    ['quantidade_em_estoque', 'valor_total']
                )

            if solicitacoes_para_atualizar:
                SolicitacaoEvento.objects.bulk_update(
                    solicitacoes_para_atualizar,
                    ['quantidade_alocada']
                )

            if transacoes_para_criar:
                TransacaoEstoque.objects.bulk_create(transacoes_para_criar)

    @admin.action(description='Gerar lista de compras')
    def baixar_lista_compras(self, request, queryset):
        try:
            id_evento = obter_id_evento_unico(queryset)
        except ValidationError as e:
            self.message_user(request, e.message, messages.ERROR)
            return

        evento = Evento.objects.get(id=id_evento)
        titulo = evento.__str__()

        itens_para_compra = queryset.filter(
            quantidade_faltando__gt=0
        ).annotate(
            nome_item=models.F('item__nome'),
            ultimo_preco_unidade_pago=models.Subquery(
                TransacaoEstoque.objects.filter(
                    item_id=models.OuterRef('item_id'),
                    tipo=TipoTransacao.COMPRA
                ).order_by(
                    '-timestamp'
                ).values(
                    'preco_unidade'
                )[:1]
            )
        ).values_list(
            'quantidade_faltando',
            'nome_item',
            'ultimo_preco_unidade_pago'
        )

        planilha_lista_compras = gerar_lista_compras(itens_para_compra, titulo)

        return HttpResponse(
            planilha_lista_compras,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': f'attachment; filename=lista_compras_{titulo.replace(' ', '_')}.xlsx'
            }
        )


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    search_fields = ('nome',)
    list_display = ('nome', 'quantidade_em_estoque', 'valor_total')
    ordering = ('-quantidade_em_estoque',)

    def has_delete_permission(self, request, obj: Item=None):
        if obj and obj.transacaoestoque_set.exists():
            return False

        return True

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return 'quantidade_em_estoque', 'valor_total'

        return ()
