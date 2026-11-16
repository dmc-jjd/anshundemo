"""文本归一化与分词的唯一之家。

为什么要集中到一处：
    归一化原先散在三处且规则各不相同——`core/tools/dedup.py:13` 把空白折成单空格、英文词
    最短 1；`core/tools/_shared.py:9` 把空白全删、英文词最短 3；`core/tools/events.py:92`
    的主题聚类干脆不经过分词，直接对原文 `str.count`。同一份数据在不同下游得到不同 token
    集，任何效果都无法单独归因。本模块是唯一实现：`import_records` 之后做**一次**，
    产出 `normalized_title` / `normalized_summary`，下游只读这两个字段。原始字段保留，
    出图与证据引用必须用原文。

第一批范围（只做纯噪声清理，删掉的必须是确定不含语义的字符/串）：
    Unicode NFKC、零宽字符、全角空格/NBSP、@提及、URL/短链、平台水印、
    「展开/收起」类角标、汉字与标点重复压缩、话题井号、空白折叠。

第二批范围（本模块同时承载，两条规则各自可归因）：
    ① `tokenize()`——唯一分词入口。jieba（HMM=False 保确定性）+ 客户词典注入，
       替换掉「汉字 bigram + 英文最长」那两套手写分词器；
    ② `strip_boilerplate_prefix()`——平台模板前缀剥离（`炸裂💥新闻：` / `突发` /
       `速看` / `来源：` / `//@` 转发链）。**只剥这五类**：`X：` 形式的地名/机构名
       前缀是信号不是噪声，剥了就是丢数据。

第一批明确不做（留给第二批之后的批次，任何时候都不许在本模块"顺手"加上）：
    繁简转换、中文数字→阿拉伯数字、日期/单位/百分比归一、同义词映射、泛化停用词过滤、
    数字串压缩——`1000000` 里的 0 是有语义的，压掉就是改数据。

`NORMALIZATION_VERSION` / `TOKENIZER_VERSION` 写进产物（`import_records` 的 artifact、
`group_by_representative` 的 `method`），用于回答「这批 token 是哪版规则切出来的」。

多包边界（M1 起，`core/packages/` 同一套三不变量）：
    ① 模块级「包派生常量」必须为零——这里没有任何词表快照，词表按当前包按需读（覆盖层）或
       在首次初始化时一次性注入（默认包）；
    ② `configure_tokenizer()` 只许启动期 / 子进程初始化期调用，绝不许请求期「切包」；
       `add_word` 没有反向操作，请求期注入 = 永久污染整个进程；
    ③ `package` 不许进 artifact payload（`TOKENIZER_VERSION` 是规则版本，不是包名）。
    两种客户词机制（`add_word` 只给默认包；其余走最长匹配覆盖层）及其语义差异见
    `configure_tokenizer()` / `tokenize()` 两个 docstring；**不要**改回并集注入——
    实测那会让「加一个客户」变成「改一次全局基线」（默认包 245/28789 条记录分词改变、
    G-GOLDEN 1675→1674 组）。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

#: 归一化规则版本。规则一变就 +1——旧 artifact 靠它区分，不靠时间戳猜。
#: v1 = 纯噪声清理（第一批）；v2 = 加平台模板前缀剥离（第二批第 2 项）。
NORMALIZATION_VERSION = 'v2'

#: 分词器版本。与 `requirements.txt` 里的 `jieba==0.42.1` 对应；HMM=False 是确定性的一部分，
#: 换版本或打开 HMM 都必须同时改这个串——否则旧 artifact 的 token 集无法归因。
TOKENIZER_VERSION = 'jieba-0.42.1-hmm_false'

#: 零宽与方向控制字符：爬虫数据常见，会把一个词在多字节层面切断成两个 token。
_ZERO_WIDTH = re.compile('[\u200b-\u200f\u202a-\u202e\u2060\ufeff]')

#: 全角空格与 NBSP：NFKC 已把它们变半角空格，这里仍显式声明——规则不走实现细节的暗示。
_SPACE_LIKE = re.compile('[\u3000\u00a0]')

#: @提及：`@平台名` 里的地名/机构名会变成向量里的实词，属于结构性污染。
_MENTION = re.compile(r'@[\w\u4e00-\u9fff.\-]{1,30}')

#: http(s) 链接：`https` / `com` 是纯噪声 token。
_URL = re.compile(r'https?://\S+')

#: 短链域名裸链接（不带 scheme）。
_SHORT_LINK = re.compile(r'(?:t\.cn|v\.douyin\.com|v\.kuaishou\.com|weibo\.com)/\S+')

#: 平台水印：`抖音号：xxx` / `微博ID xxx` 一类。
_WATERMARK = re.compile(r'(?:抖音|快手|微博|头条)(?:号|ID)\s*[:\uff1a]?\s*[\w.\-]*')

#: 交互角标：`[展开]` / `【全文】` / `[点击查看]` 一类。
_BRACKET_NOISE = re.compile(r'[\[\u3010](?:展开|收起|全文|点击查看)[\]\u3011]')

#: 话题井号：只清标记，`#话题#` 的正文保留。
_HASHTAG = re.compile('[#\uff03]')

#: 汉字重复压缩：3 个以上才压——`哈哈哈哈`→`哈`，而 `天天` / `谢谢` 是两个不同的词，不能动。
_REPEAT_CJK = re.compile(r'([\u4e00-\u9fff])\1{2,}')

#: 标点连续压缩：全角逗号句号等在 NFKC 后部分是半角，两组都列上。
_REPEAT_PUNCT = re.compile(r'([，。！？、,.!?])\1{2,}')

#: 空白折叠。
_WHITESPACE = re.compile(r'\s+')

# --------------------------------------------------------------------------- #
# 第二批第 2 项：平台模板前缀剥离
# --------------------------------------------------------------------------- #

#: 窄规则白名单。五条各自对应实测到的模板前缀，**新增一条就要有新的分布证据**：
#: `X：` 形式的账号名/地名/机构名前缀（地名 79 条、机构名数十条量级）是信息，
#: 它们不在下表里，也就不会被剥——这是刻意的，不是遗漏。
_BOILERPLATE_PREFIXES = (
    re.compile(r'^炸裂[\U0001F4A5\s]*新闻[:：]'),
    re.compile(r'^突发[!！]?[:：]?'),
    re.compile(r'^速看[!！]?[:：]?'),
    re.compile(r'^来源[:：]'),
    re.compile(r'^(?://@[^\s:：]{1,30}[:：])+'),
)

#: 护栏：剥完剩余不到这么多个字就**保留原文**。实测有几十条标题整条就是一个前缀，
#: 一剥即空——空标题会把它们并成一组"无内容事件"，比留着前缀更糟。
_PREFIX_MIN_REMAINDER = 4

#: 连续前缀（如 `突发：//@某某:正文`）最多剥这么多轮；有界循环，不赌数据形态。
_PREFIX_MAX_ROUNDS = 4


def strip_boilerplate_prefix(text: str) -> str:
    """剥掉**只在这份数据里被证实是模板**的开头串，返回新串；不满足条件原样返回。

    三条护栏，缺一条就会变成"顺手改语义"：
        ① 白名单：只剥 `_BOILERPLATE_PREFIXES` 里那五类。`关岭：` / `平坝：` 这类
           「地名或机构名 + 冒号」是账号署名，属信息，一律不剥。
        ② 剩余长度 < `_PREFIX_MIN_REMAINDER` 字时**保留原文**——整条标题只有前缀的
           记录剥完就是空串，会伪造出一个"空事件组"。
        ③ 有界循环最多 `_PREFIX_MAX_ROUNDS` 轮：连续模板（`突发：炸裂新闻：…`）要能
           一次剥净，但不能无限剥。
    """
    value = str(text or '')
    remaining = value
    for _ in range(_PREFIX_MAX_ROUNDS):
        matched = None
        for pattern in _BOILERPLATE_PREFIXES:
            stripped = pattern.sub('', remaining, count=1)
            if stripped != remaining:
                matched = stripped.lstrip()
                break
        if matched is None:
            break
        remaining = matched
    if remaining == value:
        return value
    return value if len(remaining) < _PREFIX_MIN_REMAINDER else remaining


def normalize_text(text: str) -> str:
    """把任意输入归一化为单空格分隔的纯文本；`None` / 空串返回 `''`，不抛错。

    规则顺序有依赖，不要重排：
        ① NFKC 先做——全角字母数字先变半角，后续正则才不必为全角重复一份；
           全角空格/NBSP 变半角也已由它完成（`_SPACE_LIKE` 是显式冗余，不是必要步骤）。
        ② 零宽字符必须在汉字压缩**之前**删——`哈\\u200b哈\\u200b哈` 先并成 `哈哈哈` 才能压。
        ③ 模板前缀剥离必须在 @提及清理**之前**：`//@某某:` 本身就是一个 @提及，
           先清提及会把前缀碎成 `//` + `:`，转发链就再也认不出来了。
        ④ 链接/提及/水印在压空白**之前**删——`\\S+` 依赖空白作边界。
        ⑤ 空白折叠放最后——前面所有替换都留下散落的空格与空串。
    """
    value = str(text or '')
    value = unicodedata.normalize('NFKC', value)
    value = _ZERO_WIDTH.sub('', value)
    value = _SPACE_LIKE.sub(' ', value)
    value = strip_boilerplate_prefix(value)
    value = _MENTION.sub(' ', value)
    value = _URL.sub(' ', value)
    value = _SHORT_LINK.sub(' ', value)
    value = _WATERMARK.sub(' ', value)
    value = _BRACKET_NOISE.sub(' ', value)
    value = _HASHTAG.sub('', value)
    value = _REPEAT_CJK.sub(r'\1', value)
    value = _REPEAT_PUNCT.sub(r'\1', value)
    return _WHITESPACE.sub(' ', value).strip()


def norm_or_raw(record: dict, key: str, raw_key: str) -> str:
    """取归一化字段；字段缺席（历史 artifact）才回退原文，存在但为空则如实返回空。

    为什么不能用 `record.get(key) or record.get(raw_key, '')`：`or` 把**空串**当成"字段
    不存在"。归一化后标题为空的记录（纯 `@提及` / 纯 `#话题#`）正是最该被排除的一类，
    用 `or` 会把它们的纯噪声原文重新捞回来参与分词——与归一化目的相反。
    两种情形必须分开：`None` = 字段缺席 → 回退；`''` = 归一化后确实无内容 → 保持空。
    """
    value = record.get(key)
    return record.get(raw_key, '') if value is None else value


def normalize_record(record: dict) -> dict:
    """返回带 `normalized_title` / `normalized_summary` 的**副本**，原始字段一律不动。

    不覆盖原文是硬约束：报告插图与证据引用都要回到 `title` / `summary` 的字面内容，
    归一化结果只是分词与聚类的输入面。
    """
    normalized = dict(record)
    normalized['normalized_title'] = normalize_text(record.get('title'))
    normalized['normalized_summary'] = normalize_text(record.get('summary'))
    return normalized


# --------------------------------------------------------------------------- #
# 第二批第 1 项：唯一分词入口
# --------------------------------------------------------------------------- #

#: 单字虚词黑名单：只挡**虚词**。单字实词（`人` `车` `火` `水` `死` `伤`）在突发事件
#: 标题里是核心信号，一律保留——用通用停用词表把它们一起删掉是这类数据上最常见的错误。
_STOPWORDS = frozenset(
    '的 了 是 在 和 有 就 都 而 及 与 着 或 一个 没有 我们 他们 这个 那个 什么 怎么 为什么 '
    '可以 已经 还是 但是 因为 所以 如果 虽然 然后 这样 那样 一下 一些 不是 就是 也是 还有 '
    '以及 对于 关于 通过 进行 表示 认为'.split()
)

#: 含至少一个汉字或 ASCII 字母数字才算有信息——纯标点/符号/emoji token 直接丢。
_MEANINGFUL = re.compile(r'[\u4e00-\u9fffA-Za-z0-9]')

#: 纯 ASCII 词（含数字串）。
_ASCII_WORD = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]*$')

#: 纯汉字词。
_CJK_WORD = re.compile(r'^[\u4e00-\u9fff]+$')

#: 客户词典注入词频。固定值而非 `suggest_freq`：后者会按语料动态算，同一份数据两次跑
#: 可能得到不同词频，确定性就没了。10 万远高于通用词典里最长词的频度，足以让注入词优先成词。
_CUSTOM_WORD_FREQ = 100000

#: 客户包目录（由 `configure_tokenizer()` 显式声明）。为什么不现取 `vocabulary`：
#: 工具子进程里 `vocabulary.configure()` 与 `paths.configure_package_dir()` 都还没跑，
#: 只有 `_configure_package()` 手里的这个路径是可靠的。
_TOKENIZER_PACKAGE_DIR: Path | None = None

#: 已进共享 jieba 的**那一个**包：目录 + 包名 + 已注入词集合。
#: 进 FREQ 的包有且只有一个（首个声明者），否则会全局改分词（见下方「语义差异」）。
_TOKENIZER_INJECTED_DIR: Path | None = None
_INJECTED_NAME: str | None = None
_INJECTED_WORDS: set[str] = set()

#: 非默认包的词表覆盖层：包名 → 按长度倒序的词元组（**不进 FREQ**）。
_OVERLAYS: dict[str, tuple[str, ...]] = {}

#: `current_package` 的函数引用（首次用到才导入，避免 core/text 在 import 期依赖包层）。
_CURRENT_PACKAGE_FN = None

_TOKENIZER_READY = False
_JIEBA = None


def configure_tokenizer(package_dir=None) -> None:
    """声明客户包目录（幂等，不加载词典）；由 `_configure_package()` 在子进程初始化时调用。

    **M1 起的语义（与旧版不同，别照旧注释理解）**：
      - 首次声明（jieba 还没初始化）= 决定「哪个包进共享 FREQ」：它的词表在首次 `tokenize()`
        时 `add_word` 注入（默认包 / 工具子进程各自属于这种情况）；
      - 之后声明别的包 = **只登记覆盖层**，不 `add_word`。

    为什么不并集注入（实测数据，2026-11-16）：
      先把 A 的词注入、再 `add_word` 注入 B 包 13 个词后，A 包真实语料 **245/28789 条记录的
      分词结果改变**（0.85%），G-GOLDEN 的 groups 从 1675 变 1674、哈希从 `74fde3c9…` 变
      `cc27ce37…`。根因是 `add_word` 会改**全局** `FREQ`（已有词的词频、`FREQ.total`、以及
      新词的 DAG 前缀可达性），与「A 的文本里不含 B 的词」无关，调 freq 也绕不开。
      → 所以：**新增包对既有包必须零影响**；覆盖层是正解，不是过渡方案，别"优化"回并集注入。
    """
    if package_dir is None:
        return
    global _TOKENIZER_PACKAGE_DIR
    directory = Path(package_dir)
    if not _TOKENIZER_READY:
        # 首次声明：记为「待注入的那个包」；真正注入推迟到首次 tokenize（见下）。
        _TOKENIZER_PACKAGE_DIR = directory
        return
    if _TOKENIZER_INJECTED_DIR is not None and _same_dir(directory, _TOKENIZER_INJECTED_DIR):
        return
    _register_overlay(directory)


def _same_dir(left: Path, right: Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False


def _dictionary_source_dir() -> Path | None:
    """词典来源目录：显式注入的包目录 → 宿主配置的包目录 → `None`（只用通用词典）。"""
    if _TOKENIZER_PACKAGE_DIR is not None:
        return _TOKENIZER_PACKAGE_DIR
    try:
        from core import paths
        return paths.package_dir()
    except Exception:
        return None


def _dictionary_words(package_dir: Path | None) -> list[str]:
    """客户词典：模板 `vocabulary` 的键与值 + 可选 `<package>/dict.txt`（一行一词）。

    模板那段覆盖两类词：地名 canonical 与别名、类目 label 与类目词。通用词典在复合地名与
    类目词上会切碎（例如把某开发区名切成 `X`+`经`+`开`+`区` 四个碎片），注入后才是整词；
    `dict.txt` 是客户临时加词的出口，**缺失不是错误**。

    顺序固定（localities 组、cluster_terms 组，先 label 后 values，最后 dict.txt）：
    顺序进 jieba 的注入序，改顺序会改产物。
    """
    words: list[str] = []
    if package_dir is not None:
        try:
            from core.manifest import load_template
            template = load_template(Path(package_dir))
        except Exception:
            template = {}
        vocabulary = (template or {}).get('vocabulary') or {}
        for group in ('localities', 'cluster_terms'):
            for label, values in (vocabulary.get(group) or {}).items():
                words.append(str(label))
                words.extend(str(item) for item in values)
        try:
            text = (Path(package_dir) / 'dict.txt').read_text(encoding='utf-8-sig')
            words.extend(line.strip() for line in text.splitlines())
        except OSError:
            pass
    return [word for word in words if word]


def _inject_dictionary(jieba_module, package_dir: Path | None) -> None:
    """把该包**全部**词 `add_word` 进共享 jieba（只用于默认包；同目录重复调用不重注）。

    逐词原样注入，**不做去重**：`add_word` 对重复词会再加一次词频并把 `total` 累加一次，
    而 `total` 进 `calc()` 的 `-log(total)` 项、会改变边缘切分决策——实测省掉 4 次重复注入
    就让 A 包 28789 条语料的 token 总数从 2458308 变成 2458359（+51）。听起来像"去重优化"，
    实际是改了产物，所以这里保持与改造前逐字节一致。
    """
    global _TOKENIZER_INJECTED_DIR, _INJECTED_NAME
    directory = Path(package_dir) if package_dir is not None else None
    if (directory is not None and _TOKENIZER_INJECTED_DIR is not None
            and _same_dir(directory, _TOKENIZER_INJECTED_DIR)):
        return
    for word in _dictionary_words(package_dir):
        jieba_module.add_word(word, freq=_CUSTOM_WORD_FREQ)
        _INJECTED_WORDS.add(word)
    _TOKENIZER_INJECTED_DIR = directory
    _INJECTED_NAME = directory.name if directory is not None else None
    # 注入前若有人读过该包的覆盖层，清掉：它现在是「进 FREQ 的默认包」，覆盖层必须为空
    if _INJECTED_NAME is not None:
        _OVERLAYS.pop(_INJECTED_NAME, None)


def _register_overlay(package_dir: Path) -> tuple[str, ...]:
    """登记一个非默认包的词表覆盖层（按词长倒序；只登记，不碰 jieba 的 FREQ）。"""
    package_dir = Path(package_dir)
    words = {word for word in _dictionary_words(package_dir) if len(word) >= 2}
    overlay = tuple(sorted(words, key=lambda word: (-len(word), word)))
    _OVERLAYS[package_dir.name] = overlay
    return overlay


def _current_package_name() -> str:
    global _CURRENT_PACKAGE_FN
    if _CURRENT_PACKAGE_FN is None:
        from core.packages.context import current_package
        _CURRENT_PACKAGE_FN = current_package
    return _CURRENT_PACKAGE_FN()


def _overlay(package: str | None = None) -> tuple[str, ...]:
    """当前包的覆盖层；默认包（已进 FREQ）返回空元组 → 调用方走零开销早退。

    按需登记：首次见到某个非默认包时才读它的 `template.json`（启动期仍只 scandir）。
    """
    name = package or _current_package_name()
    if not _TOKENIZER_READY:
        # 还没初始化就没有「已注入的包」，此刻登记覆盖层是错的（首次初始化会注入当前包）。
        return ()
    if name == _INJECTED_NAME:
        return ()
    overlay = _OVERLAYS.get(name)
    if overlay is not None:
        return overlay
    try:
        from core.packages import registry as _packages
        directory = _packages.package_dir(name)
    except Exception:
        _OVERLAYS[name] = ()
        return ()
    return _register_overlay(directory)


def _merge_overlay(tokens: list[str], overlay: tuple[str, ...]) -> list[str]:
    """最长匹配合并：把相邻 token 拼成覆盖层里的整词（只合并、不拆分）。

    在**过滤前**的原始 token 流上做（含标点/空白）：否则 `景区，片区` 里被过滤掉的逗号会让
    两个 token 直接相邻，拼出原文里并不存在的整词。
    """
    if not tokens or not overlay:
        return tokens
    known = set(overlay)
    longest = max(len(word) for word in overlay)
    merged: list[str] = []
    index = 0
    total = len(tokens)
    while index < total:
        joined = tokens[index]
        match_word = None
        match_end = index
        if len(joined) <= longest:
            cursor = index
            while cursor + 1 < total:
                joined = joined + tokens[cursor + 1]
                if len(joined) > longest:
                    break
                cursor += 1
                if joined in known:      # 继续往后找更长的（**最长**匹配，不是最先匹配）
                    match_word, match_end = joined, cursor
        if match_word is None:
            merged.append(tokens[index])
            index += 1
            continue
        merged.append(match_word)        # 只放**命中的整词**；`joined` 可能已越界拼接
        index = match_end + 1
    return merged


def _ensure_tokenizer():
    """首次调用时初始化 jieba（设好 cache 目录）并注入**默认包**词典；之后直接复用。"""
    global _TOKENIZER_READY, _JIEBA
    if _TOKENIZER_READY:
        return _JIEBA
    import jieba

    # jieba 默认把 `jieba.cache` 写到 `tempfile.gettempdir()`；本机 TEMP 指向仓库根，
    # 实测就在仓库根堆出一个 9MB 的 `jieba.cache` 并污染 `git status`。
    # 显式钉到项目内 `.conda/`（已 gitignore），目录建不出来才退回系统临时目录。
    jieba.setLogLevel(logging.ERROR)
    try:
        cache_dir = Path(__file__).resolve().parents[1] / '.conda'
        cache_dir.mkdir(parents=True, exist_ok=True)
        jieba.dt.tmp_dir = str(cache_dir)
    except OSError:
        pass

    _inject_dictionary(jieba, _dictionary_source_dir())
    _JIEBA = jieba
    _TOKENIZER_READY = True
    return jieba



def _keep_token(token: str) -> bool:
    """token 过滤：黑名单制——默认保留，只丢"确定不含信息"的三类。"""
    if not token or not _MEANINGFUL.search(token):
        return False
    if token in _STOPWORDS:
        return False
    if _ASCII_WORD.match(token):
        # `a` / `is` / `1` 这类单字符 ASCII 是噪声；长度 ≥2 才留。
        return len(token) >= 2
    if _CJK_WORD.match(token):
        # 单字虚词已被 `_STOPWORDS` 挡掉；剩下的单字实词必须留。
        return True
    # 中英混排（`5g基站`）：整词保留。
    return True


def tokenize(text: str, package: str | None = None) -> list[str]:
    """唯一分词入口。dedup / stage1 / stage2 / 主题聚类全部走这里。

    为什么在入口里再 `normalize_text` 一次：历史 artifact 没有 `normalized_*` 字段，
    下游会回退到原文（`norm_or_raw`）——在这一处兜住，调用方就不必记得"传进来的可能是
    脏文本"。`normalize_text` 幂等，已归一化的输入重复一次不改变结果。

    HMM=False 是确定性的前提：HMM 会按上下文动态造词，同一份数据两次跑可能不同。

    **两种「客户词」机制（语义不同，别混；这是 M1 的核心权衡）**：
      1. 默认包（首个 `configure_tokenizer` / `paths.package_dir()` 那个包）→ `add_word`
         进共享 jieba 的 `FREQ`：既影响该词本身的切分，也影响 jieba 的 DAG 前缀可达性；
      2. 非默认包 → 词表**覆盖层**：`lcut` 之后在 token 流上做**最长匹配**合并，不改 FREQ。
    两者对同一份词表的结果**可能不同**（尤其子串冲突：`社区` 命中后 `社区卫生` 会被切开），
    这是刻意的——机制 1 会全局改分词（实测让默认包 0.85% 的记录分词改变、G-GOLDEN 变红），
    所以只许一个包享用；新增包对既有包必须零影响。
    `package=None` = 当前上下文（`core.packages.context`），默认包时覆盖层为空 → 与旧版
    逐字节等价（`if overlay:` 早退，热路径零额外开销）。
    """
    value = normalize_text(text)
    if not value:
        return []
    jieba_module = _ensure_tokenizer()
    raw_tokens = jieba_module.lcut(value, HMM=False)
    overlay = _overlay(package)
    if overlay:
        raw_tokens = _merge_overlay(raw_tokens, overlay)
    return [token for token in raw_tokens if _keep_token(token)]
