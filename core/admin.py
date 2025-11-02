from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpResponse

from rangefilter.filters import DateTimeRangeFilter, DateRangeFilter

from .planilhas import gerar_checklist, gerar_lista_compras, gerar_custo_evento
from .models import Evento, TransacaoEstoque, SolicitacaoEvento, Item
from .services import alocar_quantidade_disponivel_estoque_solicitacoes, retornar_item_de_evento, alocar_item_para_evento
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
        sumario_itens_evento = SolicitacaoEvento.objects.com_sumario_de_itens(
            object_id
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
        if obj and obj.solicitacoes.filter(quantidade_alocada__gt=0).exists():
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
                case TransacaoEstoque.Tipo.ALOCACAO_EVENTO:
                    alocar_item_para_evento(obj.item.id, obj.quantidade, obj.evento.id, obj.responsavel)
                    return
                case TransacaoEstoque.Tipo.RETORNO_EVENTO:
                    retornar_item_de_evento(obj.item.id, obj.quantidade, obj.evento.id, obj.responsavel)
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

        lista_itens = queryset.get_itens_consumidos_com_preco()

        planilha_custo_evento = gerar_custo_evento(lista_itens, titulo)

        return HttpResponse(
            planilha_custo_evento,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': f'attachment; filename=Custo Evento {titulo.replace('/', '-')}.xlsx'
            }
        )


@admin.register(SolicitacaoEvento)
class SolicitacaoEventoAdmin(admin.ModelAdmin):
    autocomplete_fields = ('evento', 'item')
    list_display = ('evento', 'item', 'quantidade_solicitada' ,'quantidade_alocada')
    list_filter = (EventosEmAndamentoFilter,)
    actions = ('alocar_estoque', 'baixar_checklist_producao', 'baixar_lista_compras')

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
            headers={'Content-Disposition': f'attachment; filename=Checklist {titulo.replace('/', '-')}.xlsx'}
        )

    @admin.action(description='Alocar quantidade disponível no estoque')
    def alocar_estoque(self, request, queryset):
        try:
            _ = obter_id_evento_unico(queryset)
        except ValidationError as e:
            self.message_user(request, e.message, messages.ERROR)
            return
        alocar_quantidade_disponivel_estoque_solicitacoes(queryset, request.user)

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
            nome=models.F('item__nome'),
            ultimo_preco_unidade_pago=models.Subquery(
                TransacaoEstoque.objects.ultimo_preco_unidade_pago(models.OuterRef('item_id'))
            )
        ).values_list(
            'quantidade_faltando',
            'nome',
            'ultimo_preco_unidade_pago'
        )

        planilha_lista_compras = gerar_lista_compras(itens_para_compra, titulo)

        return HttpResponse(
            planilha_lista_compras,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': f'attachment; filename=Lista Compras {titulo.replace('/', '-')}.xlsx'
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
