from app.writing_pipeline.outlook_repair import split_outlook_fields

def test_four_items_fill_four_required_paragraphs_and_omit_optional_fifth():
    ids=['a','b','c','d','e']
    fields={key:{'optional':key=='e'} for key in ids}
    result=split_outlook_fields(ids,['甲','乙','丙','丁'],['fact'],fields)
    assert [result[key]['value'] for key in ids]==['甲','乙','丙','丁','']
    assert split_outlook_fields(ids,['甲','乙','丙','丁','戊'],['fact'],fields)['e']['value']=='戊'
    assert split_outlook_fields(ids,['甲','乙','丙'],['fact'],fields) is None

def test_optional_inserted_paragraph_is_removed_when_empty(tmp_path):
    import zipfile,io,hashlib
    from lxml import etree as E
    from core.structured_template import _schema,render_structured_docx
    path=tmp_path/'layout.docx';w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    with zipfile.ZipFile(path,'w') as z:z.writestr('word/document.xml',f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>原文</w:t></w:r></w:p></w:body></w:document>')
    fields=[{'id':'risk5','owner':'writer','optional':True,'kind':'text','value_schema':{'type':'string','minLength':0}}]
    template={'layout_source':str(path),'fields':fields,'output_schema':_schema(fields),'writer_schema':_schema(fields,True),'blocks':[{'index':0,'kind':'paragraph','parts':[{'text':'原文'}]},{'index':1000,'kind':'paragraph','insert_after_index':0,'style_from_index':0,'optional':True,'parts':[{'text':'五是'},{'field':'risk5'}]}]}
    template['source_reports']=[{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]
    for values in [{},{'risk5':{'value':'','source_refs':['fact']}}]:
        result=render_structured_docx(template,values,{'fact'},require_complete=True)
        with zipfile.ZipFile(io.BytesIO(result)) as z:root=E.fromstring(z.read('word/document.xml'))
        assert '五是' not in ''.join(root.itertext())
