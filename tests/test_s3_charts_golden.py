"""S3 出口门禁：正式报告图（Matplotlib）字节基线 + 基座零客户图表标题 + 薄壳契约。

基线来源：WP-S3-D 改码前由未改动的 `app.writer_tools.chart_payload` 录制，
逐字等于 `docs/team/任务分解-S3.md` §0.5-B；audit 记录见 `docs/team/baseline/mpl-charts-S3.json`。
PNG 内嵌 `Software=Matplotlib version<ver>` —— 升级 matplotlib 必然改字节，须重录基线并同时升级版本说明。
"""
import base64,hashlib,json
from pathlib import Path
from test_frozen_writer import fixture
from app.frozen_report import FrozenReport
from core.charts import registry

# 录制时 matplotlib==3.11.2
GOLDEN={'sentiment':'980a9a4a8aa0fff9224a14df37f958371ccb7d81a1e258a4f504373df4f09da1',
        'daily':'4f6dde78aa0629ced004833c0f30a7fc3a0c1b9f21860a9def7667d34ea5cbba',
        'platform':'c616ef84b5da84f8cca2be27532a14a1c858c3483a40f63aed88b1f7b664dd0e',
        'theme':'2c8554635c0d2bac79c291e8034e663f756252393fe887b3994c7caf6ec31741',
        'locality':'ebb7c799c86be635c8f6f24be74bba74897bfb9705bfe463bd132856c7cfed49'}
COMPOSITE='d4d58d44726c9290c2e03d8029f9f0bae1bcc00c779e5a36aebe94d72dd59e9d'
SLOTS=('title','draft_title','final_title','locality_basis')

def test_matplotlib_five_png_golden(tmp_path):
    from app.writer_tools import chart_payload
    store,_template=fixture(tmp_path);report=FrozenReport(store,'r')
    got={kind:hashlib.sha256(base64.b64decode(chart_payload(report,kind)['png_base64'])).hexdigest() for kind in GOLDEN}
    composite=hashlib.sha256(json.dumps(got,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert got==GOLDEN and composite==COMPOSITE, (
        '正式报告图 PNG 字节已变；改动基线须同时升级 matplotlib 版本说明。实际：'+json.dumps(got))

def test_base_has_no_client_chart_titles():
    repo=Path(__file__).resolve().parents[1]
    titles={c[slot] for c in registry.charts() for slot in SLOTS if c.get(slot)}
    titles={title for title in titles if len(title)>=4}
    assert len(titles)>=12, titles  # 去重后仍应覆盖客户全部图表标题口径
    files=[*sorted((repo/'core'/'charts').rglob('*.py')),
           repo/'app'/'chart_spec.py',repo/'app'/'writer_tools.py',repo/'app'/'tool.py']
    hits=[(str(path.relative_to(repo)),title) for path in files
          for title in titles if title in path.read_text(encoding='utf-8')]
    assert hits==[], hits

def test_writer_shell_contract():
    import app.writer_tools as shell
    assert shell.CHARTS==['sentiment','daily','platform','theme','locality']
    names={'frozen_statistics','query_frozen_materials','plot_frozen_chart'}
    assert set(shell.HANDLERS)==set(shell.SCHEMAS)==set(shell.DESCRIPTIONS)==names
    assert len(shell.native_tools())==3
    assert shell.plot_frozen_chart.__module__=='core.charts.renderers.matplotlib'
    assert shell.chart_payload.__module__=='core.charts.renderers.matplotlib'
    assert shell.ChartRequest.__module__=='core.charts.renderers.matplotlib'
