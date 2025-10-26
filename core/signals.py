from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.db.models import ProtectedError

from .models import Evento

@receiver(pre_delete, sender=Evento)
def proteger_solicitacao_com_itens_alocados(sender, instance: Evento, **kwargs):
    if instance.status == instance.Status.CONCLUIDO:
        return

    if (solicitacoes_com_itens_alocados := instance.itens_solicitados.filter(quantidade_alocada__gt=0)).exists():
        nomes_itens_alocados = {str(item) for item in solicitacoes_com_itens_alocados}

        mensagem_erro = (
            f'Não é possível deletar o evento {instance}. '
            'As seguintes solicitações já possuem itens alocados: '
            f'{', '.join(nomes_itens_alocados)}.'
            'Faça o retorno dos itens alocados e marque o evento como concluído antes de deletar'
        )

        raise ProtectedError(
            mensagem_erro,
            set(solicitacoes_com_itens_alocados.all())
        )