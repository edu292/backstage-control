window.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById('transacaoestoque_form');
    if (!form) return;

    let showConfirmDialog = true;

    const errorLists = form.querySelectorAll('.errorlist');
    if (!errorLists) return;

    if (errorLists.length !== 1) showConfirmDialog = false;

    errorLists.forEach((errorList) => {
        if (!errorList.classList.contains('nonfield')) showConfirmDialog = false;
        const errorItems = errorList.querySelectorAll('li')
        if (errorItems.length !== 1) showConfirmDialog = false;

        errorItems.forEach((errorItem) => {
            let errorMessage = errorItem.textContent;
            if (!errorMessage.startsWith("CONFIRMACAO_JAVASCRIPT:")) {
                showConfirmDialog = false;
            } else {
                if (showConfirmDialog) {
                    errorList.style.display = 'none';
                    document.querySelector('.errornote').style.display = 'none';
                    const confirmationMsg = errorMessage.replace('CONFIRMACAO_JAVASCRIPT: ', '');
                    const hiddenInput = form.querySelector('input[name="_confirmacao_javascript"]');
                    if (window.confirm(confirmationMsg)) {
                        hiddenInput.value = "true";
                        form.submit();
                    } else {
                        history.go(-2);
                    }
                } else {
                    errorItem.style.display = 'none';
                }
            }
        });
    });
});