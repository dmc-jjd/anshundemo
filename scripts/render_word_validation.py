"""Read-only Word COM rendering fallback when bundled LibreOffice is absent."""
import sys
from pathlib import Path
import win32com.client
import pymupdf as fitz

source=Path(sys.argv[1]).resolve();out=source.parent/'render';out.mkdir(exist_ok=True)
word=win32com.client.DispatchEx('Word.Application');word.Visible=False;word.DisplayAlerts=0
doc=None
try:
    doc=word.Documents.Open(str(source),ConfirmConversions=False,ReadOnly=True,AddToRecentFiles=False)
    doc.ExportAsFixedFormat(str(out/'report.pdf'),17)
finally:
    if doc is not None:doc.Close(False)
    word.Quit(False)
with fitz.open(out/'report.pdf') as pdf:
    for i,page in enumerate(pdf):page.get_pixmap(matrix=fitz.Matrix(1.1,1.1)).save(out/f'page-{i+1:02}.png')
    print('PAGES',len(pdf),flush=True)
