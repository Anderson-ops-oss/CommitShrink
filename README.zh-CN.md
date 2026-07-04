# CommitShrink

[![Tests](https://github.com/Anderson-ops-oss/CommitShrink/actions/workflows/tests.yml/badge.svg)](https://github.com/Anderson-ops-oss/CommitShrink/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/github/license/Anderson-ops-oss/CommitShrink)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

[English](README.md) | **简体中文**

> 一个一本正经的临床评估工具：读取你的 `git log`，输出一份《开发者心理健康评估报告》——诊断代码、量化指标，以及一条你不会照做的处方建议。

---

## 简介

CommitShrink 是一款给"从未主动求诊"的开发者准备的临床评估工具。

它读取你的 `git log`，对每一条 commit message 的情绪轨迹打分，再拿你的提交历史去对照一套内部验证过的病症分类体系，最终吐出一份完整的诊断报告：主诊断、一整套量化指标、直接引用自你本人提交历史的临床证据，以及一条你不会照做的处方建议。

底层的情感分析技术并不新——学术论文和周末小项目里都有人做过。CommitShrink 真正投入的是把这个包袱贯彻到底的诚意：诊断代码、一本正经的临床文体、经过精心校准（针对 10,000 名虚构开发者）的虚构常模数据库，以及一份由"本系统"和"本系统的一个副本"共同完成的双人复核签字。

## 示例报告节选

> 以下节选自项目的黄金样张 [`docs/report-sample.md`](docs/report-sample.md)——它是本项目的设计规格，定义了一份"正确"的报告必须长什么样。样张里的每一个数字都能用 `symptoms.yaml` 里的规则反推复现，不是随手编的。想看真实跑出来的报告，用下面的演示仓库自己生成一份。

| | |
|---|---|
| 受检者 | 示例开发者 \<dev@example.com\> |
| 评估周期 | 2026-06-22（周一）至 2026-06-28（周日） |
| 有效样本 | 47 次提交（无剔除；其中 18 条低信息量样本已计入述情统计） |
| 施测方式 | 非侵入式自然行为观察（受检者在数据产生期间对评估不知情；社会赞许性偏差 = 0，霍桑效应 = 0） |
| 评估工具 | CommitShrink v0.1 · 已通过跨文化信效度检验（n = 1）· 重测信度 r = 1.00 |

**主诉**　无。受检者未报告任何主观不适，亦无求助行为；样本系本系统主动采集。自知力：部分存在（见记录 1，03:52）。

**主诊断**　GIT-42.2 强迫性修复障碍（重度，进行性；本周单次发作达 IV 级，见记录 1）
**次诊断**　GIT-23.5 深夜绝望倾向（中度）｜ GIT-11.2 提交述情障碍（中度）
**其他临床关注状况**　GIT-70.7 魔法思维（单次发作，见记录 3）

**本周心理健康综合评分：34 / 100**（指标基础分 45 − 确诊负担 11）
较上周 −9 分，连续第 3 周下降。按当前斜率外推，预计第 30 评估周触及本量表测量下限（0 分）。

#### 记录 1 ｜ GIT-42.2 强迫性修复障碍 · 严重度 IV（极重度）

**发作时段** 06-25（周四）02:14 – 03:52，持续 98 分钟

```
02:14  a3f9c21  fix login bug
02:31  8be0d47  fix login bug again
02:58  f10a9b3  really fix login bug
03:22  90cc1ea  PLEASE WORK
03:52  6d2e8f0  ok it was a typo
```

**临床解读**　98 分钟内对同一问题实施 5 次干预。语言模态依次经历陈述（02:14）、重申（02:31）、强调（02:58）、祈祷（03:22）四个阶段，符合本障碍的典型病程。判级依据：链长 5、链中出现全大写样本、整链位于 00:00–05:59，三项 IV 级条件同时满足。03:52 病识感恢复（"ok it was a typo"），恢复过程伴随轻度自尊损耗。

## 工作原理

```
collector.py  →  analyzer.py  →  diagnoser.py  →  report.py
   读取 git log     情感打分         病症匹配         渲染报告
   （单次调用）
```

1. **Collector** 用一次 `git log --numstat` 读完整个仓库——不调用任何外部服务，数据不出本机。
2. **Analyzer** 给每条 commit message 打情绪分（VADER + 手工校准的中英双语词典补丁），并算出六项核心指标。
3. **Diagnoser** 拿提交模式去匹配病症表——每条诊断、严重度阈值、处方语，全部作为数据存在 [`commit_shrink/data/symptoms.yaml`](commit_shrink/data/symptoms.yaml) 里，不写死在代码里。
4. **Report** 把结果渲染成一份完整的临床报告——可以是终端输出，也可以是交互式的 Streamlit 网页版。

## 安装

需要 Python 3.10+。

```bash
git clone https://github.com/<your-username>/commit-shrink.git
cd commit-shrink
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## 使用方法

```bash
commit-shrink                                # 评估当前目录，最近 7 天
commit-shrink path/to/repo                   # 评估指定仓库
commit-shrink . --days 30                    # 拉长评估周期
commit-shrink . --author you@example.com     # 指定评估某一位贡献者
commit-shrink . --until 2026-06-28T23:59:00+08:00
commit-shrink . --card card.html             # 额外写出一张可分享的 HTML 评估卡

# 评估一个公开仓库，不用自己先手动 clone：
commit-shrink github:torvalds/linux --author torvalds@linux-foundation.org --days 7
commit-shrink https://github.com/owner/repo --author dev@example.com

# 评估某个 GitHub 用户的全部公开仓库，合并为一条时间线：
commit-shrink gh-user:torvalds --author torvalds@linux-foundation.org --days 30
```

远程地址（`github:owner/repo` 简写，或任意 `https://`/`git@` clone 地址）会以 *blobless 部分克隆* 的方式拉到一个临时目录（保留完整历史元数据，文件内容仅在评估周期内按需惰性拉取），用完即删，不留痕迹。评估远程仓库时必须指定 `--author`——没有这个参数，工具没有任何合理依据去猜"你想看的是哪位贡献者"，所以干脆拒绝擅自挑一个提交最多的人当受检者。

`gh-user:<用户名>` 更进一步：它会发现该用户的公开仓库（owned，按最近推送排序），把它们**合并成一条提交时间线**一起评估，并让跨周趋势锚定到"人"而非某个仓库——这样用户新增或归档仓库时趋势也不会断。同样必须指定 `--author`（填邮箱）；范围是该用户在窗口内有活动的自有公开仓库。评估他"贡献过但不拥有"的仓库、以及私有仓库，暂不在范围内。

不想拿自己的提交历史冒险？生成一个"病情丰富"的演示仓库直接体验：

```bash
python scripts/make_fixture.py --path fixture-repo
```

这个脚本会围绕"最近一个完整的周一至周日"构造历史，并打印出评估它所需的确切命令，例如：

```bash
commit-shrink fixture-repo --days 7 --until 2026-06-28T23:59:00+08:00
```

照着它打印出来的那一行执行（`--until` 的值每天都不同）——如果不带 `--until` 直接跑 `commit-shrink fixture-repo --days 7`，评估窗口默认以*今天*结尾，会漏掉演示历史里的大部分提交。

## 分享卡

`--card <路径>` 会额外写出一张自包含的单页 HTML"出院小结"——含病例号、心理健康指数刻度条、主诊断和一条处方，专为浏览器打开后截图发群里而设计。它不引用任何外部资源，离线也能渲染。Streamlit 网页版会内联展示同一张卡片，并附下载按钮。

## 网页版

更喜欢浏览器界面？同一套评估流程也提供了 Streamlit 网页版，用交互式 Plotly 情绪图表替代了终端版的字符走势图。

```bash
pip install -e ".[web]"
streamlit run commit_shrink/web_app.py
```

## 病症速览

完整病症分类表（17 条）在 [`commit_shrink/data/symptoms.yaml`](commit_shrink/data/symptoms.yaml)，这里先看几条：

| 代码 | 病名 | 触发场景 |
|---|---|---|
| GIT-42.2 | 强迫性修复障碍 | `fix` → `fix again` → `really fix` → `PLEASE WORK` |
| GIT-60.1 | 命名系统性崩溃 | `final` → `final_v2` → `final_v2_REAL_FINAL` |
| GIT-31.0 | 决策后悔综合征 | `Revert "Revert ..."`——对后悔本身的后悔 |
| GIT-99.0 | P0 级心理事件 | 凌晨四点的 `hotfix` |
| GIT-11.2 | 提交述情障碍 | 四分之一的提交信息只写了"update" |
| GIT-45.0 | CI 讨好障碍 | `fix ci` → `please pass` → `make ci green` |
| GIT-00.1 | 空提交存在焦虑 | 一次什么都没改的 `--allow-empty` 提交 |

## 免责声明

本报告由自动化系统基于 `git log` 生成，不构成医疗建议，但可能构成 code review 建议。报告中全部"病症"均为对量化评估文体的戏仿；个别病名系临床术语向 git 领域的移植——本报告的评估对象是提交历史，而非任何人本身，不指涉任何真实精神疾病或其患者。

本工具用于自我评估。未经同意对同事的仓库运行本工具所得的诊断均属无效——而这个行为本身，也已经构成一种本中心尚未编码的病症。

## 许可协议

[MIT](LICENSE) © 2026 Anderson Cheng
