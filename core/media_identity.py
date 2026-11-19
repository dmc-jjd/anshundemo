"""Explicit media identity normalization; no client names or fuzzy merges."""
from collections import Counter
import re
import unicodedata

GENERIC={'微信公众号','微信','微博','新浪微博','网站','移动客户端','客户端','视频','抖音','今日头条','头条','百家号','搜狐','搜狐APP','其他','未知','纸媒','电视','快手','小红书','腾讯网','新浪看点','UC','QQ浏览器','有驾','腾讯新闻','百度','新浪','网易','搜狐新闻','新浪新闻'}

def normalize(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value or ''))).strip()

def unresolved(name):
    return not name or name in GENERIC or name.split('-')[0] in GENERIC or bool(re.match(r'^第[A-Z]?\d+版',name))

def organization_counts(rows,aliases,suffixes=()):
    from .frozen_report import MissingReportInput
    mapping={normalize(k):normalize(v) for k,v in aliases.items()}
    if any(not k or not v for k,v in mapping.items()):raise ValueError('empty_organization_alias')
    allowed={normalize(s) for s in suffixes}
    roots=set(mapping)|set(mapping.values())
    # An observed complete name is an exact anchor, never a fuzzy similarity guess.
    for row in rows:
        name=normalize(row.get('author'))
        if unresolved(name):name=normalize(row.get('source'))
        if not unresolved(name) and '-' not in name:roots.add(name)
    def canonical(name):
        if name in mapping:return mapping[name]
        for root in sorted(roots,key=lambda value:(-len(value),value)):
            if name.startswith(root+'-') and all(part in allowed for part in name[len(root)+1:].split('-')):
                return mapping.get(root,root)
        return name
    counts=Counter();missing=[]
    for row in rows:
        author=normalize(row.get('author'));source=normalize(row.get('source'))
        name=canonical(author)
        if unresolved(name):name=canonical(source)
        if unresolved(name):
            missing.append(str(row.get('id')));continue
        counts[name]+=1
    if missing:raise MissingReportInput('缺少可核实的媒体机构身份：'+','.join(missing[:12])+f'；共{len(missing)}条，请在客户包补机构别名，不以账号Id代替。')
    return dict(sorted(counts.items(),key=lambda pair:(-pair[1],pair[0])))
