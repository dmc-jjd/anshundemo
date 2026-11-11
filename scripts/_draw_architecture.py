"""绘制架构重构框架的 5 张图 → docs/*.png（修正版）"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib import font_manager

font_manager.fontManager.addfont('C:/Windows/Fonts/msyh.ttc')
plt.rcParams['font.family'] = 'Microsoft YaHei'
plt.rcParams['axes.unicode_minus'] = False

CORE = '#2d7895'; CORE_F = '#eaf2f7'
PORT = '#b8860b'; PORT_F = '#fdf3e0'
PKG  = '#2e7d32'; PKG_F  = '#e9f5ea'
API  = '#5b6c77'; API_F  = '#f1f4f6'
INF  = '#8a97a0'; INF_F  = '#f2f4f5'
RED  = '#9b2734'; RED_F  = '#fdf1f0'
TXT  = '#1f2a33'
ARROW = '#334b5c'
OUT = 'docs'

def new_fig(w, h, xr, yr):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(*xr); ax.set_ylim(*yr); ax.axis('off')
    fig.patch.set_facecolor('white')
    return fig, ax

def box(ax, x, y, w, h, text, fc, ec, fs=10.5, lw=1.6, bold=False, tc=TXT):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=1.0',
                                fc=fc, ec=ec, lw=lw, zorder=2))
    ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fs, color=tc,
            fontweight='bold' if bold else 'normal', linespacing=1.35, zorder=3)

def arrow(ax, x1, y1, x2, y2, color=ARROW, lw=2.0):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='-|>', color=color, lw=lw, mutation_scale=18), zorder=4)

def label(ax, x, y, text, fs=11, color=TXT, ha='center', bold=False):
    ax.text(x, y, text, ha=ha, va='center', fontsize=fs, color=color,
            fontweight='bold' if bold else 'normal', zorder=5)

# ------------------------------------------------------------ 图1 分层
def fig_layers():
    fig, ax = new_fig(12, 9.5, (0, 120), (0, 100))

    def layer(yb, yt, title, tcolor, items, item_fs=10.5):
        ax.add_patch(FancyBboxPatch((4, yb), 112, yt-yb, boxstyle='round,pad=0,rounding_size=1.6',
                                    fc='white', ec=tcolor, lw=2.4, zorder=1))
        ax.text(7.5, yt-4.2, title, ha='left', va='center', fontsize=13.5, fontweight='bold', color=tcolor, zorder=3)
        n = len(items); iy0 = yb + 2.4; iy1 = yt - 9.0; gap = 2.6
        bw = (112 - 10 - (n+1)*gap) / n
        for i, it in enumerate(items):
            box(ax, 9 + gap + i*(bw+gap), iy0, bw, iy1-iy0, it, 'white', tcolor, fs=item_fs)

    ax.add_patch(FancyBboxPatch((4, 3), 112, 13, boxstyle='round,pad=0,rounding_size=1.6', fc=INF_F, ec=INF, lw=2.2))
    ax.text(7.5, 12.6, '① 基础设施', ha='left', va='center', fontsize=13.5, fontweight='bold', color=INF)
    box(ax, 9, 4.6, 102, 6.4, 'LangGraph  ·  模型  ·  SQLite  ·  OOXML  ·  图表库', INF_F, INF, fs=11.5)

    layer(22, 46, '② 客户包 Packages（按客户 / 报告类型维护）', PKG,
          ['安顺月报包\n模板+工具+图表\n+技能+提示词', '客户 B 包\n（新报告类型）', '客户 C 包\n（……）'], item_fs=11)
    layer(52, 78, '③ 编排基座 Core Runtime（客户无关 · 只做一次）', CORE,
          ['图编排\n引擎', '审校循环\n引擎', 'Agent\n运行器', '工具\n执行器', '状态·工件\n存储', '模型\n客户端'], item_fs=10)
    layer(84, 99, '④ 交付与接入层', API,
          ['Web 工作台', 'HTTP API（通用任务生命周期）'], item_fs=12)

    arrow(ax, 60, 82.8, 60, 79.2)   # 交付 → 基座
    arrow(ax, 60, 50.8, 60, 47.2)   # 基座 → 客户包
    fig.savefig(f'{OUT}/架构分层图.png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)

# ------------------------------------------------------------ 图2 依赖倒置
def fig_di():
    fig, ax = new_fig(12.5, 7.2, (0, 125), (0, 72))
    def column(x0, x1, title, tcolor, items, item_fs=10):
        ax.add_patch(FancyBboxPatch((x0, 6), x1-x0, 60, boxstyle='round,pad=0,rounding_size=1.6', fc='white', ec=tcolor, lw=2.4))
        ax.text(x0+2.2, 62.6, title, ha='left', va='center', fontsize=12.5, fontweight='bold', color=tcolor)
        n = len(items); gap = 2.0; bh = (60 - 10 - (n+1)*gap) / n
        for i, it in enumerate(items):
            box(ax, x0+2.6, 9 + gap + i*(bh+gap), x1-x0-5.2, bh, it, 'white', tcolor, fs=item_fs, lw=1.5)
    column(3, 37, '编排基座\n（只依赖接口）', CORE, ['图编排引擎', '工具执行器', 'Agent 运行器', '审校循环引擎'], 10.5)
    column(44, 81, '核心接口 Ports\n（稳定契约）', PORT, ['Tool', 'AgentRole', 'Reviewer', 'TemplateProvider', 'SkillProvider', 'GraphSpec'], 9.5)
    column(88, 122, '客户包\n（实现接口 · 注册）', PKG, ['安顺月报包', '客户 B 包', '客户 C 包'], 10.5)
    arrow(ax, 37.6, 36, 43.4, 36); label(ax, 40.5, 39.5, '调用', fs=10, color=ARROW)
    arrow(ax, 87.4, 36, 81.6, 36); label(ax, 84.5, 39.5, '实现并注册', fs=10, color=ARROW)
    label(ax, 62.5, 2, '基座与客户包互不直接引用 —— 只通过接口连接', fs=11)
    fig.savefig(f'{OUT}/依赖倒置图.png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)

# ------------------------------------------------------------ 图3 现状 vs 目标
def fig_now_target():
    fig, ax = new_fig(12.5, 6.4, (0, 125), (0, 64))
    ax.add_patch(FancyBboxPatch((3, 6), 55, 52, boxstyle='round,pad=0,rounding_size=1.6', fc=RED_F, ec=RED, lw=2.4))
    ax.text(30.5, 54.2, '现状 · 单体内混杂', ha='center', fontsize=13, fontweight='bold', color=RED)
    for i, it in enumerate(['main.py\n全部路由', 'workflow.py\n图 + 业务', 'tool.py\n工具 + 安顺口径',
                            'agent.py\n提示词 + 安顺口径', 'reviewers.py\n循环 + 文风']):
        box(ax, 6.5, 43 - i*9.2, 48, 7.6, it, 'white', RED, fs=10)
    ax.add_patch(FancyBboxPatch((67, 6), 55, 52, boxstyle='round,pad=0,rounding_size=1.6', fc=PKG_F, ec=PKG, lw=2.4))
    ax.text(94.5, 54.2, '目标 · 基座 + 客户包', ha='center', fontsize=13, fontweight='bold', color=PKG)
    box(ax, 70.5, 42, 48, 10.5, 'core/ 编排基座\n（客户无关 · 只做一次）', CORE_F, CORE, fs=10.5)
    box(ax, 70.5, 30, 48, 9, 'packages/ 安顺月报包', 'white', PKG, fs=10.5)
    box(ax, 70.5, 18.5, 48, 9, 'packages/ 客户 B 包', 'white', PKG, fs=10.5)
    box(ax, 70.5, 7.5, 48, 9, 'packages/ 客户 C 包', 'white', PKG, fs=10.5)
    arrow(ax, 59, 32, 66, 32, lw=3)
    label(ax, 62.5, 35.5, '重构', fs=11.5, color=ARROW, bold=True)
    fig.savefig(f'{OUT}/现状vs目标.png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)

# ------------------------------------------------------------ 图4 客户包解剖
def fig_package():
    fig, ax = new_fig(11, 7.6, (0, 110), (0, 76))
    box(ax, 39, 32, 32, 12, 'manifest.yaml\n（包的唯一入口）', PORT_F, PORT, fs=11.5, bold=True, lw=2.2)
    top = [('template.json\n模板结构+字段绑定', 5), ('tools/\n工具声明（schema+能力）', 37), ('charts/\n图表定义', 72)]
    bot = [('skills/\n文风·来源绑定·校验', 5), ('prompts/\n角色定义+提示词', 39), ('graph 规格\n审校角色·轮次·路由', 74)]
    for text, x in top: box(ax, x, 60, 30, 11, text, PKG_F, PKG, fs=9.8)
    for text, x in bot: box(ax, x, 10, 30, 11, text, PKG_F, PKG, fs=9.8)
    for cx in (20, 52, 87): arrow(ax, cx, 59.6, 55, 44.4, color=PORT, lw=1.8)
    for cx in (20, 54, 89): arrow(ax, cx, 21.4, 55, 32.2, color=PORT, lw=1.8)
    label(ax, 55, 2.5, 'manifest.yaml 是唯一入口，基座据此登记资源并组合执行图', fs=11, color=PORT, bold=True)
    fig.savefig(f'{OUT}/客户包结构图.png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)

# ------------------------------------------------------------ 图5 新客户接入流程
def fig_onboard():
    fig, ax = new_fig(15, 4.2, (0, 150), (0, 40))
    steps = [('复制包骨架', CORE), ('写 template.json', CORE), ('声明工具·图表·技能', CORE),
             ('写提示词', CORE), ('改 manifest.yaml', PORT), ('注册 / 加载', PORT),
             ('基座组合图并运行', PKG), ('新客户上线', PKG)]
    n = len(steps); bw = 15.5; gap = 2.6
    for i, (t, c) in enumerate(steps):
        x = 4 + i*(bw+gap)
        box(ax, x, 12, bw, 15, t, 'white', c, fs=9.6, lw=1.8, bold=(i == n-1), tc=(PKG if i == n-1 else TXT))
        if i < n-1:
            arrow(ax, x+bw+0.1, 19.5, x+bw+gap-0.1, 19.5, lw=2.0)
    label(ax, 75, 3.5, '全程不改 core/ 基座', fs=11.5, color=PKG, bold=True)
    fig.savefig(f'{OUT}/新客户接入流程图.png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)

fig_layers(); fig_di(); fig_now_target(); fig_package(); fig_onboard()
print('DONE 5 pngs')
