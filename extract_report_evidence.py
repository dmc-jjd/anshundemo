from pathlib import Path
import json,re,collections
p=Path('report_work');rows=json.loads((p/'all_records.json').read_text(encoding='utf-8'))
patterns={'屯堡文化':'何以中国.*(地戏|屯堡|石.*书)|六百年家国|一块.*脸子','特色产业':'38个亿元|一颗金刺梨|关岭以果治荒|订单萝卜|烤小肠|新能源汽车.*下壳','赛事文旅':'环贵州.*(安顺|黄果树)|国际高桥|游客手机在黄果树|今年以来接待游客超六百','民生治理':'155名养老|急危重症部正式|安顺解决上万居民|科技教育实验校|帮务工者追回','峰值长征':'长征|红军|泸定|大渡河'}
lines=[]
for name,pat in patterns.items():
 rs=[r for r in rows if re.search(pat,str(r['标题'] or ''))]
 if name=='峰值长征':rs=[r for r in rs if str(r['发布时间']).startswith('2026-10-22')]
 lines.append(f'【{name}】标题规则 {pat} 匹配 {len(rs)}')
 seen=set()
 for r in rs:
  if r['标题'] in seen:continue
  seen.add(r['标题'])
  lines.append(f"{r['发布时间']} [{r['来源信息']}/{r['作者']}/{r['媒体级别']}] {r['标题']}\n摘要：{str(r['摘要'] or '')[:450]}\n网址：{r['网址']}")
  if len(seen)>=14:break
neg=[r for r in rows if r['舆情调性']=='负面']
lines.append('负面平台 '+str(collections.Counter(r['媒体环节'] for r in neg)))
lines.append('URL重复 '+str(len(rows)-len(set(r['网址'] for r in rows))))
lines.append('标题重复 '+str(len(rows)-len(set(r['标题'] for r in rows))))
(p/'report_evidence.txt').write_text('\n\n'.join(lines),encoding='utf-8')
print('Evidence saved')
