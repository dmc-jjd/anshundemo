from pathlib import Path
import json,re,collections,math
from PIL import Image,ImageDraw,ImageFont
from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH,WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.chart import BarChart,LineChart,Reference
R=Path.cwd(); W=R/'report_work'; O=R/'交付成果';O.mkdir(exist_ok=True)
S=json.loads((W/'october_statistics.json').read_text(encoding='utf-8'));D=json.loads((W/'all_records.json').read_text(encoding='utf-8'));N=S['total'];neg=[r for r in D if r['舆情调性']=='负面']
pct=lambda n,base=N:f'{n/base*100:.2f}%'
rules=[
('涉平坝、安顺中院的商品房诉讼投诉','空气证据|魔术办案|执法霸凌|幽灵协议|造假窝点|曾永涛|集体造假法律文书',None,'跨年诉讼投诉；主张待核'),
('沪昆高速安顺段辅助驾驶退出、追尾讨论','辅助驾驶|智驾系统|高速NOA|智驾突然','安顺|沪昆','事故日期、经过待核'),
('黄果树皮划艇赛前演练落水视频','(?s)(黄果树.*皮划艇|皮划艇.*黄果树)',None,'报道转述景区回应'),
('贵阳银行安顺分行处罚及人员禁业','(?s)(贵阳银行.*(安顺|禁业|受贿|行贿)|安顺分行.*(处罚|被罚))',None,'监管处罚报道'),
('平坝齐伯镇矿山爆破、房屋受损投诉','(?s)((齐伯|齐佰).*(爆破|放炮|房屋|搬扦)|(爆破|放炮|房屋|搬扦).*(齐伯|齐佰))',None,'网民诉求；责任待核'),
('蒋贵川接受审查调查报道','蒋贵川',None,'涉嫌违纪违法调查'),
('安顺竹荪种植大棚火灾报道','(?s)((大棚|竹荪).*(火灾|起火|着火|大火)|(火灾|起火).*(大棚|竹荪))','安顺','报道指向10月13日火灾'),
('黄果树游客与摆渡车通行争执','(?s)黄果树.*(摆渡车|不让行|不让路|不给司机让路|堵路哥)',None,'短视频；经过待核'),
('张学喜接受审查调查报道','张学喜',None,'普定监察调查关联'),
('安顺经开区充电棚火灾责任讨论','充电棚',None,'2025年火灾旧事新议')]
T=[]
for name,pat,extra,nature in rules:
 inds=[i for i,r in enumerate(D,2) if re.search(pat,str(r['标题'] or '')+'\n'+str(r['摘要'] or '')) and (not extra or re.search(extra,str(r['标题'] or '')+'\n'+str(r['摘要'] or '')))]
 rs=[D[i-2] for i in inds];ns=[r for r in rs if r['舆情调性']=='负面']
 T.append(dict(name=name,pattern=pat,extra=extra or '',nature=nature,total=len(rs),negative=len(ns),indices=inds,first=min(r['发布时间'] for r in rs),last=max(r['发布时间'] for r in rs),sample=next((r for r in rs if r['舆情调性']=='负面'),rs[0])))
T.sort(key=lambda t:t['negative'],reverse=True)
(W/'report_topic_statistics.json').write_text(json.dumps(T,ensure_ascii=False,indent=2),encoding='utf-8')
# High-resolution charts, matching the source report's blue/orange/grey palette.
FONT=r'C:\Windows\Fonts\msyh.ttc';BOLD=r'C:\Windows\Fonts\msyhbd.ttc';BLUE='#5B9BD5';ORANGE='#ED7D31';GREY='#A5A5A5';INK='#222222'
def f(n,b=False):return ImageFont.truetype(BOLD if b else FONT,n)
def canvas(h):
 im=Image.new('RGB',(1800,h),'white');return im,ImageDraw.Draw(im)
def txt(dr,xy,s,size=34,fill=INK,anchor=None,b=False):dr.text(xy,str(s),font=f(size,b),fill=fill,anchor=anchor)
def save(im,n):p=W/n;im.save(p,dpi=(300,300));return p
im,dr=canvas(850)
vals=list(S['sentiment'].values());colors=[BLUE,ORANGE,GREY];start=-90
for v,c in zip(vals,colors):
 end=start+360*v/N;dr.pieslice((130,55,870,795),start,end,fill=c);start=end
# donut center
dr.ellipse((335,260,665,590),fill='white');txt(dr,(500,400),'28,789',50,anchor='mm',b=True);txt(dr,(500,455),'条监测记录',29,anchor='mm')
for i,(k,v) in enumerate(S['sentiment'].items()):
 y=200+i*170;dr.rectangle((1040,y,1086,y+46),fill=colors[i]);txt(dr,(1125,y-3),k,42,b=True);txt(dr,(1125,y+60),f'{v:,}条  /  {pct(v)}',38)
chart1=save(im,'fig1_sentiment.png')
im,dr=canvas(860);L,Tp,RR,BB=120,65,1730,660;maxv=2000
for v in range(0,2001,500):
 y=BB-(BB-Tp)*v/maxv;dr.line((L,y,RR,y),fill='#DDDDDD',width=2);txt(dr,(L-20,y),str(v),28,anchor='rm')
points=[]
for i,(date,v) in enumerate(S['daily'].items()):
 x=L+(RR-L)*i/30;y=BB-(BB-Tp)*v/maxv;points.append((x,y));txt(dr,(x,BB+35),str(i+1),27,anchor='mt')
dr.line(points,fill=BLUE,width=6)
for i,(x,y) in enumerate(points):
 dr.ellipse((x-5,y-5,x+5,y+5),fill=BLUE)
 if i in [0,1,2,14,20,21,30]:txt(dr,(x,y-20),list(S['daily'].values())[i],29,anchor='mb',b=True)
txt(dr,(920,BB+90),'2026年10月（日期）',32,anchor='mt');txt(dr,(120,20),'条',28)
txt(dr,(120,790),'注：曲线反映所提供工作簿的逐日记录量，不能据此确认全网采集完整性。',27,fill='#555555')
chart2=save(im,'fig2_daily.png')
def bars(mapping,name,height=900,base=N):
 im,dr=canvas(height);items=list(mapping.items());l=350;right=1390;top=55;step=(height-100)/len(items);maxn=max(mapping.values())*1.08
 for i,(k,v) in enumerate(items):
  y=top+i*step;txt(dr,(l-30,y+step*.28),k,33,anchor='rm');length=(right-l)*v/maxn;dr.rectangle((l,y+8,l+length,y+step*.55),fill=BLUE);txt(dr,(l+length+20,y+step*.28),f'{v:,}  ({pct(v,base)})',30,anchor='lm')
 return save(im,name)
chart3=bars(S['platform'],'fig3_platform.png',940)
chart4=bars({'已预警':1861,'未预警':2053},'fig4_negative_warning.png',430,3914)
chart5=bars(S['negative_platform'],'fig5_negative_platform.png',850,3914)
# A separate audit workbook with recalculated values and exact matching rules.
wb=Workbook();ws=wb.active;ws.title='统计口径';ws.append(['项目','说明']);
for row in [('数据来源','安顺市委10月总数据.xlsx / 03101627'),('统计单位','原始记录条数；含转载和重复议题，不等于独立事件或人数'),('日期范围',S['date_min']+' 至 '+S['date_max']),('日期分组','按原始发布时间日期；未验证采集完整性'),('总记录',N),('负面记录',3914),('已预警记录',1861),('分类/区县','事件分类全部为空；无区县字段；不输出对应占比'),('核验边界','热点来自标题与摘要；未独立核实原始新闻及投诉主张'),('TOP10说明','选取10个关注议题，按匹配负面记录数排序；非全库所有议题排名')]:ws.append(row)
for name,mapping,base in [('情绪分布',S['sentiment'],N),('信源分布',S['platform'],N),('负面信源',S['negative_platform'],3914),('逐日数量',S['daily'],N),('负面预警',{'已预警':1861,'未预警':2053},3914)]:
 ws=wb.create_sheet(name);ws.append(['项目','记录数','占比'])
 for k,v in mapping.items():ws.append([k,v,v/base]);ws.cell(ws.max_row,3).number_format='0.00%'
 if name!='逐日数量':ws.append(['合计',sum(mapping.values()),sum(mapping.values())/base]);ws.cell(ws.max_row,3).number_format='0.00%'
 chart=LineChart() if name=='逐日数量' else BarChart();chart.title=name;chart.add_data(Reference(ws,min_col=2,min_row=1,max_row=1+len(mapping)),titles_from_data=True);chart.set_categories(Reference(ws,min_col=1,min_row=2,max_row=1+len(mapping)));chart.width=22;chart.height=11;ws.add_chart(chart,'E2')
ws=wb.create_sheet('重点议题匹配');ws.append(['序号','关注议题','匹配总记录','其中负面','最早发布时间','最晚发布时间','主正则表达式','附加正则表达式','性质边界','原始数据Excel行号'])
for i,t in enumerate(T,1):ws.append([i,t['name'],t['total'],t['negative'],t['first'],t['last'],t['pattern'],t['extra'],t['nature'],','.join(map(str,t['indices']))])
ws=wb.create_sheet('议题样本');ws.append(['序号','关注议题','发布时间','原标题','来源信息','原调性','网址','摘要摘录'])
for i,t in enumerate(T,1):
 r=t['sample'];ws.append([i,t['name'],r['发布时间'],r['标题'],r['来源信息'],r['舆情调性'],r['网址'],re.sub(r'1[3-9]\d{9}','[联系方式略]',str(r['摘要'] or ''))[:450]])
for ws in wb:
 ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
 for c in ws[1]:c.font=Font(name='微软雅黑',bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='366092');c.alignment=Alignment(vertical='center',wrap_text=True)
 ws.row_dimensions[1].height=28
 for row in ws.iter_rows(min_row=2):
  for c in row:c.font=Font(name='微软雅黑',size=10);c.alignment=Alignment(vertical='top',wrap_text=True)
 for c in ws.columns:ws.column_dimensions[c[0].column_letter].width=22 if c[0].column==1 else 35
 if ws.title=='重点议题匹配':
  for c in ['B','G','H','I']:ws.column_dimensions[c].width=50
  ws.column_dimensions['J'].width=65
 if ws.title=='议题样本':
  for c in ['B','D','G','H']:ws.column_dimensions[c].width=60
xlsx=O/'2026年10月安顺市网络舆情统计校验表.xlsx';wb.save(xlsx)
# Word report: source masthead, Chinese official-report typography and numbered sections.
doc=Document();sec=doc.sections[0];sec.page_width=Cm(21);sec.page_height=Cm(29.7);sec.top_margin=Cm(2.5);sec.bottom_margin=Cm(2.5);sec.left_margin=Cm(2.6);sec.right_margin=Cm(2.6);sec.header_distance=Cm(1);sec.footer_distance=Cm(1.2)
normal=doc.styles['Normal'];normal.font.name='Times New Roman';normal.font.size=Pt(16);normal._element.rPr.rFonts.set(qn('w:eastAsia'),'仿宋');normal.paragraph_format.line_spacing=Pt(25);normal.paragraph_format.space_after=Pt(0)
for st in ['Heading 1','Heading 2']:
 style=doc.styles[st];style.font.name='Times New Roman';style._element.rPr.rFonts.set(qn('w:eastAsia'),'黑体' if st=='Heading 1' else '楷体');style.font.size=Pt(16);style.font.color.rgb=RGBColor(0,0,0);style.paragraph_format.line_spacing=Pt(28);style.paragraph_format.space_before=Pt(8);style.paragraph_format.space_after=Pt(4)
def font(run,size=16,east='仿宋',bold=False):
 run.font.name='Times New Roman';run.font.size=Pt(size);run.bold=bold;run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),east)
def para(text='',style=None,size=16,indent=True):
 p=doc.add_paragraph(style=style);p.paragraph_format.widow_control=True
 if indent:p.paragraph_format.first_line_indent=Pt(size*2)
 font(p.add_run(text),size, '黑体' if style=='Heading 1' else ('楷体' if style=='Heading 2' else '仿宋'))
 return p
def head(text,level=1):return para(text,'Heading '+str(level),indent=True)
def page():doc.add_page_break()
def figure(path,caption,h=None):
 p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.line_spacing=1;p.paragraph_format.keep_with_next=True
 p.add_run().add_picture(str(path),width=Cm(15.5))
 p=para(caption,size=12,indent=False);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.line_spacing=Pt(20);p.paragraph_format.space_after=Pt(10)
def small(text):
 p=para(text,size=11,indent=False);p.paragraph_format.line_spacing=Pt(18);p.paragraph_format.space_after=Pt(4);return p
# footer
p=sec.footer.paragraphs[0];p.alignment=WD_ALIGN_PARAGRAPH.CENTER;font(p.add_run('— '),11)
fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');p._p.append(fld);font(p.add_run(' —'),11)
# masthead, no unconfirmed issue/sign-off date.
p=doc.add_paragraph();p.paragraph_format.space_before=Pt(30);p.paragraph_format.space_after=Pt(24);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;font(p.add_run('网络舆情分析报告'),38,'宋体',True)
p=para('2026年第10期',size=16,indent=False);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.space_after=Pt(20)
p=para('中共安顺市委网信办                         2026年11月（编制稿）',size=12,indent=False)
borders=OxmlElement('w:pBdr');border=OxmlElement('w:bottom');border.set(qn('w:val'),'single');border.set(qn('w:sz'),'12');borders.append(border);p._p.get_or_add_pPr().append(borders)
p=para('安顺市2026年10月网络舆情分析报告',size=21,indent=False);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.space_before=Pt(20);p.paragraph_format.space_after=Pt(20);p.paragraph_format.line_spacing=Pt(30);font(p.runs[0],21,'宋体',True)
head('一、涉安信息传播态势')
para(f'（一）从总体来看，所提供监测工作簿共收录10月信息28789条，约2.88万条。其中正面13642条，占{pct(13642)}；中性11233条，占{pct(11233)}；负面3914条，占{pct(3914)}（含重复议题及转载，详见图1）。逐日记录量峰值为10月22日1909条，占全月{pct(1909)}（详见图2）；当日长征主题转载较多，同时收录环贵州自行车赛安顺赛段、军工技能竞赛等本地报道。已预警记录1861条，均标注为负面，占全部记录{pct(1861)}。')
small('口径说明：本报告总量、调性及平台统计沿用原工作簿记录和标签，未经逐条地域清洗；传播记录量不等于独立事件数。热点分析另行核对本地关联和旧闻背景，未据此推算全网总量。')
page()
figure(chart1,'图1 舆情情绪分布图（单位：条／百分比）')
figure(chart2,'图2 舆情信息逐日数量图（单位：条）')
small('统计范围：2026年10月1日04:54至10月31日23:51，按原始发布时间分组；前3日仅收录119条，采集覆盖是否完整无法从现有文件确认，不据此判断现实舆情冷暖。')
page()
para(f'（二）从平台上看，10月监测记录主要分布于移动客户端、网站、微信公众号、视频、微博、纸媒、电视和互动栏目。其中移动客户端10183条，占{pct(10183)}；网站6356条，占{pct(6356)}；微信公众号5679条，占{pct(5679)}；视频4012条，占{pct(4012)}；微博1766条，占{pct(1766)}；纸媒750条，占{pct(750)}；电视36条，占{pct(36)}；互动栏目7条，占{pct(7)}（详见图3）。前三类合计22218条，占{pct(22218)}，构成监测记录的主要来源。')
figure(chart3,'图3 舆情信源分布图（单位：条／百分比）')
para('从具体内容看，屯堡文化、特色产业、项目建设、桥旅融合、体育赛事和民生服务等议题在新闻网站与客户端传播；涉房司法投诉、景区视频和群众诉求则呈现多次发布、多平台转发的特点。平台分布反映采集记录结构，不等同于用户覆盖率或传播影响力。')
small('注：图3按原字段“媒体环节”统计；原工作簿将部分微信视频号记录归入“微信公众号”，本报告保留原分类。')
page()
para('（三）从内容上看，本月具有明确本地关联的正面报道，主要围绕文化传承、产业发展、文旅赛事和公共服务展开。中国新闻网、天眼新闻、安顺市广播电视台等平台，以及中青在线、海外网等署名来源，在相关记录中出现。')
para('一是屯堡文化与非遗活化受到关注。“何以中国｜地戏回响：六百年屯堡，文脉未断”“何以中国｜六百年家国，刻在一张地戏面具上”“一块‘脸子’引来6万游客”等报道，将地戏、傩雕、村落文化与乡村旅游相结合，形成具有地方辨识度的传播内容。')
para('二是特色产业和项目建设提供发展叙事。“38个亿元项目里的安顺投资吸引力”“贵州安顺：一颗金刺梨的三张答卷”“贵州关岭以果治荒‘唤醒’山地经济”“平坝：订单萝卜‘拔’出好钱景”“安顺新能源汽车电池下壳体产业聚势成链”等报道，集中呈现招商引资、山地农业和产业链培育。')
para('三是桥旅融合和赛事活动丰富文旅表达。环贵州自行车赛安顺赛段、坝陵河大桥高桥极限运动、云峰屯堡面具艺术周等内容，以赛事场景、自然景观和文化体验带动城市形象传播；游客手机落水后工作人员协助找回的报道，则体现景区服务细节。')
para('四是公共服务和基层治理形成民生支撑。“西秀区155名养老机构从业人员持证上岗”“普定县人民医院急危重症部正式开科运行”“安顺解决上万居民‘上下’烦心事”等记录，涉及养老照护、医疗服务和居民生活。建议围绕服务效果持续跟踪，以具体进展增强报道可信度。')
page()
para(f'（四）从负面舆情看，原始工作簿标注负面信息3914条。其中已预警1861条，占负面记录{pct(1861,3914)}；未预警2053条，占{pct(2053,3914)}（详见图4）。预警是原数据中的标记，不能据此认定为已核实、已处置或已去重的事件。')
figure(chart4,'图4 负面记录预警标记分布（单位：条／百分比）')
para('从重点议题看，涉平坝、安顺中院的商品房诉讼投诉持续传播，相关规则匹配793条，其中负面786条；记录仅涉及12个作者名称，前三个名称合计发布774条，反映出较强的重复传播特征。有关“造证”“包庇”等内容属于发帖者主张，现有资料不能验证，不能将发布量解读为案件数量或支持人数。')
para('安全与服务类内容同样值得关注。沪昆高速安顺段辅助驾驶退出、黄果树皮划艇赛前演练落水视频、安顺竹荪种植大棚火灾及景区摆渡车通行争执等，在本月形成转载与讨论。贵阳银行安顺分行处罚、干部审查调查报道，以及齐伯镇矿山周边居民反映的房屋与居住安全诉求，涉及金融内控、公共形象和基层矛盾化解。')
small('说明：事件分类字段全部为空，且无区县归属和处置结果字段，故不沿用8月模板中的分类占比、区县占比和“会同处置数量”。图4改用可核验的预警结构。')
page()
figure(chart5,'图5 负面舆情信源分布（单位：条／占负面记录比例）')
np=S['negative_platform'];top3=list(np.items())[:3]
para('负面信息的传播渠道与整体信源结构存在差异。'+ '；'.join(f'{k}{v}条，占负面记录{pct(v,3914)}' for k,v in top3)+'。应结合不同平台的表达方式开展核验：对高频文本投诉辨明同一诉求的反复发布，对短视频核对拍摄时间、地点和上下文，对媒体转载追溯原始消息来源。')
para('需要注意“旧事新议”与本月新发事件的区别。经开区充电棚火灾责任讨论的摘要指向2025年10月事故；部分情杀、超期羁押等转载涉及多年以前的案件。此类内容可纳入再传播风险观察，但不能据其10月发布时间认定为本月新发事故或案件。')
small('注：图5替代8月模板的区县分布图，避免依据标题猜测区县后形成不可靠统计。')
page()
p=para('表1 本月涉安重点关注议题TOP10',size=16,indent=False);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.space_after=Pt(12);font(p.runs[0],16,'黑体')
small('选取具有本地关联及公共风险的10个关注议题，按规则匹配的负面记录数排序。该表为选题观察清单，未穷尽全库议题；数量不代表独立事件数或全网热度。')
table=doc.add_table(rows=1,cols=4);table.style='Table Grid';table.autofit=False
for c,w in zip(table.columns,[1,7.1,2.1,5.2]):c.width=Cm(w)
for c,text in zip(table.rows[0].cells,['序号','关注议题','负面条数','性质及边界']):c.text=text
for i,t in enumerate(T,1):
 cells=table.add_row().cells
 for c,text in zip(cells,[str(i),t['name'],str(t['negative']),t['nature']]):c.text=text
for ri,row in enumerate(table.rows):
 trPr=row._tr.get_or_add_trPr();cant=OxmlElement('w:cantSplit');trPr.append(cant)
 if ri==0:
  repeat=OxmlElement('w:tblHeader');trPr.append(repeat)
 for ci,c in enumerate(row.cells):
  for p in c.paragraphs:
   p.paragraph_format.line_spacing=Pt(19);p.paragraph_format.space_after=Pt(5);p.paragraph_format.space_before=Pt(5)
   if ci in [0,2]:p.alignment=WD_ALIGN_PARAGRAPH.CENTER
   for r in p.runs:font(r,12,'宋体',ri==0)
  if ri==0:
   sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'E7EDF5');c._tc.get_or_add_tcPr().append(sh)
small('统计说明：对“标题＋摘要”按附录规则检索，并筛选原调性为负面的记录；同一记录在单个议题内计一次，议题间可能重叠，不加总为负面事件总数。原始标签不等于核实结论。')
small('核查重点：银行处罚记录不等同本月新发刑案；“接受审查调查”不等于认定犯罪；张学喜相关信息与普定监察调查有关，不能据此认定其为安顺地方干部；旧火灾的责任讨论应与事故发生时间分开表述。')
page()
head('二、月度风险研判')
head('（一）研判分析',2)
para('从10月样本看，正面传播以屯堡文化、特色产业和文旅赛事为支撑；风险议题则集中于既有涉房司法诉求、安全事件画面传播及基层民生矛盾。传播结构提示，需把持续性投诉、突发性安全讨论和旧闻再传播分别研判，不能仅按发帖量判断风险程度。')
para('一是涉房司法诉求具有持续累积风险。相关投诉引用2023年至2025年的诉讼材料，反复使用强烈指控性表述，并通过多标题发布和@媒体扩大触达。若案件事实、程序解释和诉求办理情况缺乏可理解的信息，可能继续被转述为司法公信力问题。建议核对原始文书和诉求清单，在依法保护隐私的前提下说明可公开事实、程序与救济渠道，避免以笼统回应替代实质沟通。')
para('二是文旅赛事热度与安全质疑可能相互叠加。黄果树皮划艇演练视频、游客与摆渡车通行争执等，容易在短视频中脱离完整语境。样本报道转述景区称落水选手已获救、状态良好，但现有材料不能替代后续核查。应及时交代活动性质、现场保障、救援经过及整改安排，对景区交通和游客服务问题给出具体改进，防止个案争议牵连城市文旅形象。')
para('三是民生安全诉求与责任争议存在跨领域扩散可能。大棚火灾报道、矿山爆破与房屋受损投诉、充电棚旧火灾赔偿讨论，分别指向生产生活空间安全、企业与居民关系、公共设施管理等问题。若只回应传播表象而未核实安全隐患和办理进度，诉求可能持续累积。应将现场排查、责任核查、诉求反馈和信息公开同步推进，形成可追踪的办理记录。')
page()
head('（二）工作建议',2)
para('1.关注入冬消防与生产生活场所安全风险。10月大棚火灾报道和充电棚旧火灾责任讨论，提示生产场所用电、可燃材料管理、充电设施与人员住宿等环节需要持续排查。进入11月，取暖用火用电需求增加，应把种植大棚、仓储场所、出租房、老旧小区和电动自行车集中充电点纳入巡查重点，核对电气线路、疏散通道及消防设施情况。')
para('建议消防、应急、农业农村、住建和属地乡镇根据职责形成隐患台账，明确整改责任与反馈时限；对生产经营场所违规住人、飞线充电等问题依法处置，兼顾群众实际需求完善替代设施。发生事故后及时发布已核实的基本情况与救援进展，对原因调查和责任认定保持阶段性表述，避免用未经核实的视频内容代替调查结论。')
para('2.关注秋冬文旅活动、道路交通与辅助驾驶讨论风险。赛事、高桥体验、景区游览等活动可带来传播热度，也可能因单个安全画面引发质疑。建议文旅、体育、交通运输、公安及活动组织方加强联动，对涉水活动、临崖区域、观光车接驳和游客步行交叉路段开展针对性检查，完善恶劣天气下的停运、限流、退改与告知安排。')
para('对落水演练、通行争执等视频，先核对拍摄时间、活动性质和完整经过，再发布清晰说明，避免信息碎片化放大误解。围绕高速行车和辅助驾驶，开展面向驾驶人的风险提示，强调持续观察道路、主动接管和保持安全车距；涉及具体事故责任的争议，应以交警调查和合法有效证据为依据。')
page()
para('3.关注涉房、矿山周边居民及其他长期诉求的重复传播风险。对涉平坝商品房诉讼投诉、齐伯镇矿山周边居民反映的问题，应区分事实争议、法律程序、安全隐患和补偿诉求，逐项梳理办理状态。重复发布既可能反映同一诉求未获得有效沟通，也可能放大个案的可见度，应同时核对诉求实质和传播来源。')
para('建议属地与相关部门建立可追踪的沟通清单，对矿山爆破、房屋损伤等线索开展现场核实，必要时依法组织专业检测，反馈核查依据和后续安排。对诉讼相关投诉说明法定程序与救济路径，对欠薪、物业服务等民生问题落实受理、转办、办理、回访闭环；不得以发布次数替代事实判断，也不把未经核实的指控直接转述为结论。')
para('4.关注金融内控信息、调查通报与消费维权议题叠加风险。银行处罚和干部审查调查信息容易与历史案件被拼接转载，形成超出原通报范围的联想；11月促销活动增多，价格宣传、预售退款、配送售后等也可能形成新的群众诉求。建议相关部门和机构对照原始处罚决定、调查通报和业务规则进行解释，准确区分行政处罚、纪律审查、监察调查与刑事裁判。')
para('对消费投诉加强线索研判和依法办理，对合理诉求明确反馈时间，对共性问题集中公开规则与办理进展。同时完善监测数据质量管理：补齐事件分类、区县归属、关联事件编号、核验状态和处置结果，区分原发与转载、旧闻与新事、投诉主张与查证事实。下一期在同口径数据基础上开展月度比较，提升预警和复盘的可用性。')
page()
head('附：统计口径与核验说明')
small('1. 数据依据：本报告仅依据用户提供的10月工作簿及8月报告模板编制。工作簿明细表“03101627”有28789条记录；情绪及平台汇总已与“Sheet1”“Sheet5”逐项核对。未增补外部新闻，不将样本中的处置说法视为已独立确认的最新进展。')
small('2. 全量统计：按原调性、媒体环节和发布时间计算。原始监测含全国性主题报道、部分异地内容和广告，尚未逐条清洗，故正文使用“工作簿收录”“监测记录”等表述。百分比保留两位小数，分项因四舍五入可能不严格等于100%。未据8月模板数据计算环比、同比。')
small('3. 字段限制：“事件分类”28789条均为空，无区县归属、阅读量、互动量、处置结果及独立事件编号；“已预警”1861条均属负面标签，只能解释为预警记录。无法计算与8月“去重重点预警事件”同口径的数量。')
small('4. 热点筛选：结合本地关联、集中传播和公共风险选取10个议题，按匹配负面记录数排序，不作为全库所有议题的绝对热度榜。匹配规则作用于“标题＋摘要”，单议题内每条记录计一次，不按作者去重；议题间允许重叠。具体规则、原表行号和样本网址见配套统计校验表。')
small('5. 时间与事实：发布时间只代表本月收录传播时间。商品房诉讼投诉有跨年案件背景，经开区充电棚火灾指向2025年；其他旧案转载不计为本月新发事件。投诉使用“反映、称、质疑”等归属措辞，事故及调查信息以“样本报道转述”或“接受调查”表述，不补写未提供的结论。')
p=para('重点议题匹配核对表',size=13,indent=False);font(p.runs[0],13,'黑体')
tab=doc.add_table(rows=1,cols=4);tab.style='Table Grid'
for c,t in zip(tab.rows[0].cells,['序号','主检索词／规则摘要','总记录','负面记录']):c.text=t
abbrev=['空气证据／魔术办案等','辅助驾驶等，且含安顺或沪昆','黄果树与皮划艇共现','贵阳银行与安顺、禁业等共现','齐伯或齐佰与爆破、房屋等共现','蒋贵川','大棚或竹荪与火灾等，且含安顺','黄果树与摆渡车、不让行等共现','张学喜','充电棚']
for i,(t,key) in enumerate(zip(T,abbrev),1):
 for c,s in zip(tab.add_row().cells,[str(i),key,str(t['total']),str(t['negative'])]):c.text=s
for row in tab.rows:
 for c in row.cells:
  for p in c.paragraphs:
   p.paragraph_format.line_spacing=Pt(16);p.paragraph_format.space_after=Pt(1)
   for r in p.runs:font(r,10,'宋体')
small('注：主检索词摘要用于阅读提示；精确计算以配套表中的Python正则表达式和附加条件为准。')
# Metadata and save
props=doc.core_properties;props.title='安顺市2026年10月网络舆情分析报告';props.subject='依据10月监测数据编制';props.author='';props.keywords='安顺;2026年10月;网络舆情;月度分析';props.comments='基于用户提供工作簿编制，详见统计口径说明。'
path=O/'2026年10月安顺市网络舆情分析报告.docx';doc.save(path)
# Reopen saved artifacts and assert key statistics and structure.
check=Document(path);texts='\n'.join(p.text for p in check.paragraphs)+'\n'+'\n'.join(c.text for t in check.tables for row in t.rows for c in row.cells)
assert len(check.inline_shapes)==5
assert len(check.tables)==2
assert all(str(v) in texts for v in [28789,13642,11233,3914,1861,1909])
assert '2026年第8期' not in texts and '272条' not in texts
assert sum(S['sentiment'].values())==N==sum(S['platform'].values())==sum(S['daily'].values())
assert sum(S['negative_platform'].values())==3914
assert [t['negative'] for t in T]==[786,296,157,145,102,94,90,82,39,11]
ck=load_workbook(xlsx,data_only=False);assert ck['统计口径']['B6'].value==28789
for name,total in [('情绪分布',N),('信源分布',N),('负面信源',3914),('负面预警',3914)]:assert ck[name].cell(ck[name].max_row,2).value==total
validation={'record_total':N,'sentiment_sum':sum(S['sentiment'].values()),'platform_sum':sum(S['platform'].values()),'daily_sum':sum(S['daily'].values()),'negative_platform_sum':sum(S['negative_platform'].values()),'figures':len(check.inline_shapes),'tables':len(check.tables),'topic_negative_counts':[t['negative'] for t in T],'outputs':[str(path),str(xlsx)]}
(W/'validation_results.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
(W/'report_final_text.txt').write_text(texts,encoding='utf-8')
print(json.dumps(validation,ensure_ascii=False))
