import base64
import io
import zipfile

from app.export import export_docx
from core.storage import Store


def test_legacy_draft_chart_export_uses_supplied_instance_store(tmp_path, monkeypatch):
    import app.export as export
    import app.storage as storage
    import core.layout as layout
    import core.charts.spec as charts
    path = tmp_path / 'layout.docx'
    document = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><w:body><w:p><w:r><w:t>{{CHART_1}}</w:t></w:r></w:p><w:p><w:r><w:drawing><a:blip/></w:drawing></w:r></w:p></w:body></w:document>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', document)
        archive.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    monkeypatch.setattr(layout, 'docx_path', lambda package: path)
    monkeypatch.setattr(layout, 'source_docx_path', lambda package: path)
    monkeypatch.setattr(charts, 'declared_charts', lambda package: [{'id': 'test'}])
    monkeypatch.setattr(export, 'template_values', lambda *args: {'marker': 'value'})
    stores = [Store(tmp_path / name, package='anshun_monthly') for name in ('first', 'second')]
    refs = [s.put_artifact('task', 'chart', {'png_base64': base64.b64encode(name.encode()).decode()})
            for s, name in zip(stores, ('first-png', 'second-png'))]
    def forbidden(*args, **kwargs):
        raise AssertionError('export must not open deployment storage')
    monkeypatch.setattr(storage, 'Store', forbidden)
    for store, ref, expected in zip(stores, refs, (b'first-png', b'second-png')):
        raw = export_docx({'fact_ref': 'facts', 'sections': []},
                          {'result_refs': {'render_chart:test': ref}}, None, 'draft', [], local_store=store)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            assert archive.read('word/media/chart_1.png') == expected
