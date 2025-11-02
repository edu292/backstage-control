import io
import xlsxwriter


def _adicionar_estilos_base(workbook):
    estilos = {
        'title': workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#D9D9D9',
            'font_size': 12,
            'border': 1
        }),
        'header': workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#F2F2F2',
            'border': 1
        }),
        'qty': workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        }),
        'item': workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        }),
        'money': workbook.add_format({
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'num_format': 'R$ #,##0.00'
        }),
        'total_label': workbook.add_format({
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#F2F2F2',
            'border': 1
        }),
        'total_money': workbook.add_format({
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#F2F2F2',
            'num_format': 'R$ #,##0.00'
        })}

    return estilos


def _setup_planilha(worksheet_name, nome_evento, col_span):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet(worksheet_name)

    estilos = _adicionar_estilos_base(workbook)

    worksheet.set_row(0, 25)
    worksheet.set_row(1, 30)

    worksheet.merge_range(0, 0, 0, col_span - 1, nome_evento, estilos['title'])

    worksheet.repeat_rows(0, 1)

    worksheet.set_portrait()
    worksheet.set_paper(9)

    worksheet.fit_to_pages(1, 0)

    worksheet.center_horizontally()

    worksheet.set_footer('&CPágina &P de &N')

    return output, workbook, worksheet, estilos


def _finalizar_planilha(workbook, output):
    workbook.close()
    output.seek(0)
    return output.getvalue()


def gerar_checklist(lista_itens, nome_evento):
    col_count = 5
    output, workbook, worksheet, estilos = _setup_planilha('Checklist', nome_evento, col_count)

    worksheet.set_column(0, 0, 5)  # QTD
    worksheet.set_column(1, 1, 40)  # Item
    worksheet.set_column(2, 2, 12)  # Saída
    worksheet.set_column(3, 3, 12)  # Montagem
    worksheet.set_column(4, 4, 12)  # Retorno

    headers = ['QTD', 'ITEM', 'SAÍDA', 'MONTAGEM', 'RETORNO']
    worksheet.write_row(1, 0, headers, estilos['header'])

    row = 2
    for quantidade, item in lista_itens:
        worksheet.write(row, 0, quantidade, estilos['qty'])
        worksheet.write(row, 1, item, estilos['item'])
        worksheet.insert_checkbox(row, 2, False, estilos['qty'])
        worksheet.insert_checkbox(row, 3, False, estilos['qty'])
        worksheet.insert_checkbox(row, 4, False, estilos['qty'])
        row += 1

    return _finalizar_planilha(workbook, output)


def gerar_lista_compras(itens_para_compra, nome_evento):
    col_count = 4
    output, workbook, worksheet, estilos = _setup_planilha('Lista Compras', nome_evento, col_count)

    worksheet.set_column(0, 0, 12)  # Quantidade
    worksheet.set_column(1, 1, 40)  # Item
    worksheet.set_column(2, 2, 15)  # Último Preço Unidade
    worksheet.set_column(3, 3, 15)  # Preço Estimado Item

    headers = ['Quantidade', 'Item', 'Último Preço Un.', 'Preço Estimado']
    worksheet.write_row(1, 0, headers, estilos['header'])

    row = 2
    custo_total_estimado = 0
    for quantidade_comprar, item, ultimo_preco_pago_unidade,  in itens_para_compra:
        if not ultimo_preco_pago_unidade:
            ultimo_preco_pago_unidade = 0

        custo_item_estimado = quantidade_comprar * ultimo_preco_pago_unidade
        custo_total_estimado += custo_item_estimado

        worksheet.write(row, 0, quantidade_comprar, estilos['qty'])
        worksheet.write(row, 1, item, estilos['item'])
        worksheet.write(row, 2, ultimo_preco_pago_unidade, estilos['money'])
        worksheet.write(row, 3, custo_item_estimado, estilos['money'])
        row += 1

    worksheet.merge_range(row, 0, row, 2, 'Preço Total Estimado', estilos['total_label'])
    worksheet.write(row, 3, custo_total_estimado, estilos['total_money'])

    return _finalizar_planilha(workbook, output)


def gerar_custo_evento(itens_consumidos, nome_evento):
    col_count = 4
    output, workbook, worksheet, estilos = _setup_planilha('Custo Evento', nome_evento, col_count)

    worksheet.set_column(0, 0, 12)  # Quantidade
    worksheet.set_column(1, 1, 40)  # Item
    worksheet.set_column(2, 2, 15)  # Preço Unidade
    worksheet.set_column(3, 3, 15)  # Custo Total Item

    headers = ['Quantidade', 'Item', 'Preço Unidade', 'Custo Total Item']
    worksheet.write_row(1, 0, headers, estilos['header'])

    row = 2
    custo_total = 0
    for quantidade_consumida, item, preco_unidade in itens_consumidos:
        custo_item = quantidade_consumida * preco_unidade
        custo_total += custo_item

        worksheet.write(row, 0, quantidade_consumida, estilos['qty'])
        worksheet.write(row, 1, item, estilos['item'])
        worksheet.write(row, 2, preco_unidade, estilos['money'])
        worksheet.write(row, 3, custo_item, estilos['money'])
        row += 1

    worksheet.merge_range(row, 0, row, 2, 'Custo Total', estilos['total_label'])
    worksheet.write(row, 3, custo_total, estilos['total_money'])

    return _finalizar_planilha(workbook, output)
