"""Synthetic, distributable fixtures; no customer data or generated exchanges."""
import hashlib
import zipfile


def switch_template(tmp_path):
    from core.structured_template import _schema
    fields = []
    parts = []
    for key, label in [('b17_total_info', '总量'), ('b17_positive', '正面'),
                       ('b17_negative', '负面'), ('b17_key_warning', '重点预警')]:
        if parts:
            parts.append({'text': '，'})
        parts.extend([{'text': label}, {'field': key}])
        fields.append({'id': key, 'owner': 'data', 'kind': 'text', 'semantic': label,
                       'display_name': label, 'sources': [{'text': '数值'}],
                       'value_schema': {'type': 'string'}})
    parts.append({'text': '。'})
    fields.extend([
        {'id': 'b30_top_issue_categories', 'owner': 'data', 'kind': 'text',
         'semantic': 'TOP10类别', 'sources': [{'text': '类别'}], 'value_schema': {'type': 'string'}},
        {'id': 'b34_top10_rows', 'owner': 'data', 'kind': 'table', 'semantic': 'TOP10',
         'binding': {'tool': 'top10_events'}, 'sources': [{'text': '内容'}],
         'value_schema': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'string'}}}},
    ])
    blocks = [
        {'index': 0, 'kind': 'paragraph', 'parts': parts},
        {'index': 1, 'kind': 'paragraph', 'parts': [{'text': '其中，涉及'}, {'field': 'b30_top_issue_categories'}, {'text': '问题。'}]},
        {'index': 2, 'kind': 'paragraph', 'parts': [{'text': 'TOP10'}]},
        {'index': 3, 'kind': 'table', 'headers': ['内容'], 'parts': [{'field': 'b34_top10_rows'}]},
    ]
    body = '<w:p><w:r><w:t>总量数值，正面数值，负面数值，重点预警数值。</w:t></w:r></w:p>'
    body += '<w:p><w:r><w:t>其中，涉及类别问题。</w:t></w:r></w:p><w:p><w:r><w:t>TOP10</w:t></w:r></w:p>'
    body += '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>内容</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>内容</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    path = tmp_path / 'switch-layout.docx'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '</w:body></w:document>')
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    return {'id': 'synthetic-switch-template', 'status': 'confirmed_by_human',
            'layout_source': str(path), 'source_reports': [{'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, {'sha256': 'synthetic-second-source'}],
            'comparison_ref': 'synthetic-comparison', 'fields': fields, 'blocks': blocks,
            'output_schema': _schema(fields), 'writer_schema': _schema(fields, True)}
