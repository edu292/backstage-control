from django import forms
from django.db import models
from django.core.exceptions import ValidationError

from .models import TransacaoEstoque, SolicitacaoEvento, TipoTransacao


class TransacaoEstoqueAdminForm(forms.ModelForm):
    _confirmacao_javascript = forms.BooleanField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = TransacaoEstoque
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('tipo') == TipoTransacao.ALOCACAO_EVENTO:
            item = cleaned_data.get('item')
            evento = cleaned_data.get('evento')
            quantidade = cleaned_data.get('quantidade')
            confirmacao_javascript = cleaned_data.get('_confirmacao_javascript')
            try:
                solicitacao = SolicitacaoEvento.objects.get(item=item, evento=evento)
            except SolicitacaoEvento.DoesNotExist:
                if confirmacao_javascript:
                    solicitacao = SolicitacaoEvento.objects.create(evento=evento, item=item, quantidade_solicitada=quantidade)
                else:
                    raise ValidationError(
                        f'CONFIRMACAO_JAVASCRIPT: Não existe uma solicitação para {item.nome} este evento!\n'
                        'Tem certeza que deseja continuar?'
                    )

            if quantidade > solicitacao.quantidade_faltando:
                quantidade_a_mais = quantidade - solicitacao.quantidade_faltando
                if confirmacao_javascript:
                    solicitacao.quantidade_solicitada = models.F('quantidade_solicitada') + quantidade_a_mais
                    solicitacao.save(update_fields=('quantidade_solicitada',))
                else:
                    raise ValidationError(
                        f'CONFIRMACAO_JAVASCRIPT: Você está alocando {quantidade_a_mais} itens a mais do que o solicitado!\n'
                        'Tem certeza que deseja continuar?'
                    )

        return cleaned_data