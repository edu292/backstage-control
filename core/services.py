from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.functions import Coalesce

from .models import SolicitacaoEvento, TransacaoEstoque, Item, Evento

def alocar_item_para_evento(id_item, quantidade_a_alocar, id_evento, responsavel):
    if quantidade_a_alocar <= 0:
        raise ValidationError({'quantidade': 'A Quantidade deve ser positva'})

    with transaction.atomic():
        try:
            solicitacao = SolicitacaoEvento.objects.select_for_update().get(evento_id=id_evento, item_id=id_item)
        except SolicitacaoEvento.DoesNotExist:
            raise ValidationError('Não existe uma solicitação para o item no evento')

        TransacaoEstoque.objects.create(
            item_id=id_item,
            tipo=TransacaoEstoque.Tipo.ALOCACAO_EVENTO,
            quantidade=quantidade_a_alocar,
            evento_id=id_evento,
            responsavel=responsavel,
        )

        solicitacao.quantidade_alocada = models.F('quantidade_alocada') + quantidade_a_alocar
        solicitacao.save()


def retornar_item_de_evento(id_item, quantidade_a_retornar, id_evento, responsavel):
    if not Evento.objects.filter(id=id_evento).exists():
        raise ValidationError({'id_evento': 'Não existe nenhum evento com o id informado'})

    try:
        item = Item.objects.select_for_update().get(id=id_item)
    except Item.DoesNotExist:
        raise ValidationError({'id_item': 'Não existe nenhum item com o id informado'})

    agregados = TransacaoEstoque.objects.filter(
        evento_id=id_evento,
        item_id=id_item
    ).aggregate(
        quantidade_alocada=Coalesce(
            models.Sum(
                models.F('quantidade'),
                filter=models.Q(tipo=TransacaoEstoque.Tipo.ALOCACAO_EVENTO)
            ),
            models.Value(0)
        ),
        quantidade_retornada=Coalesce(
            models.Sum(
                models.F('quantidade'),
                filter=models.Q(tipo=TransacaoEstoque.Tipo.RETORNO_EVENTO)
            ),
            models.Value(0)
        )
    )

    quantidade_disponivel_retorno = agregados['quantidade_alocada'] - agregados['quantidade_retornada']

    if quantidade_a_retornar > quantidade_disponivel_retorno:
        raise ValidationError({
            'quantidade_a_retornar': 'Não é possível retornar mais itens do que foram alocados. '
                                     f'Quantidade disponível para retorno {quantidade_disponivel_retorno}'
        })

    quantidade_retornada_anterior_total = agregados['quantidade_retornada']

    alocacoes = TransacaoEstoque.objects.filter(
        evento_id=id_evento,
        item_id=id_item,
        tipo=TransacaoEstoque.Tipo.ALOCACAO_EVENTO
    ).order_by(
        'timestamp'
    ).values_list(
        'quantidade',
        'preco_unidade'
    )

    transacoes_criar = []

    with transaction.atomic():
        for quantidade_alocada, preco_unidade in alocacoes:
            quantidade_retornada_anterior_alocacao = min(quantidade_retornada_anterior_total, quantidade_alocada)
            saldo_liquido = quantidade_alocada - quantidade_retornada_anterior_alocacao
            quantidade_retornada_anterior_total -= quantidade_retornada_anterior_alocacao

            if saldo_liquido <= 0:
                continue

            if quantidade_a_retornar <= 0:
                break

            quantidade_retornada_atual_alocacao = min(saldo_liquido, quantidade_a_retornar)
            item.quantidade_em_estoque += quantidade_retornada_atual_alocacao
            item.valor_total += quantidade_retornada_atual_alocacao * preco_unidade

            transacoes_criar.append(
                TransacaoEstoque(
                    item_id=id_item,
                    tipo=TransacaoEstoque.Tipo.RETORNO_EVENTO,
                    evento_id=id_evento,
                    quantidade=quantidade_retornada_atual_alocacao,
                    preco_unidade=preco_unidade,
                    responsavel=responsavel
                )
            )

            quantidade_a_retornar -= quantidade_retornada_atual_alocacao

        TransacaoEstoque.objects.bulk_create(transacoes_criar)
        item.save(update_fields=('quantidade_em_estoque', 'valor_total'))


def alocar_quantidade_disponivel_estoque_solicitacoes(solicitacoes, user):
    transacoes_para_criar = []
    solicitacoes_para_atualizar = []

    solicitacoes_para_processar = solicitacoes.filter(quantidade_faltando__gt=0)

    ids_itens_para_travar = solicitacoes_para_processar.values('item_id')

    with transaction.atomic():
        items_map = {
            item.id: item for item in
            Item.objects.select_for_update().filter(id__in=ids_itens_para_travar, quantidade_em_estoque__gt=0)
        }

        for solicitacao in solicitacoes_para_processar:
            item = items_map.get(solicitacao.item.id)

            if not item:
                continue

            quantidade_a_alocar = min(item.quantidade_em_estoque, solicitacao.quantidade_faltando)

            item.quantidade_em_estoque -= quantidade_a_alocar
            item.valor_total -= quantidade_a_alocar * item.preco_medio


            transacoes_para_criar.append(
                TransacaoEstoque(
                    tipo=TransacaoEstoque.Tipo.ALOCACAO_EVENTO,
                    evento=solicitacao.evento,
                    item=item,
                    quantidade=quantidade_a_alocar,
                    responsavel=user,
                    preco_unidade=item.preco_medio
                )
            )

            solicitacao.quantidade_alocada += quantidade_a_alocar
            solicitacoes_para_atualizar.append(solicitacao)

        if items_map:
            Item.objects.bulk_update(
                items_map.values(),
                ['quantidade_em_estoque', 'valor_total']
            )

        if solicitacoes_para_atualizar:
            SolicitacaoEvento.objects.bulk_update(
                solicitacoes_para_atualizar,
                ['quantidade_alocada']
            )

        if transacoes_para_criar:
            TransacaoEstoque.objects.bulk_create(transacoes_para_criar)
