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

## 示例报告（实时）

下面这一节不是编的——它是本仓库自己跑出来的 CommitShrink 评估结果，由[一个 GitHub Action](.github/workflows/update-readme-example.yml) 每周直接读取本仓库的 git log 自动重新生成。版式遵循项目的黄金样张 [`docs/report-sample.md`](docs/report-sample.md)——它定义了一份"正确"的报告必须长什么样；想生成属于你自己的一份，用下面的演示仓库。

<!-- COMMITSHRINK:LIVE-EXAMPLE:START -->

_本节由本仓库自身的提交历史自动生成 — 最近更新于 2026-07-06 10:17 UTC。_

## CommitShrink™ 开发者心理健康评估中心

**周期性心理状态评估报告 · 第 28 评估周**

| | |
|---|---|
| 受检者 | Anderson-ops-oss <u3606584@connect.hku.hk> |
| 评估周期 | 2026-06-30 — 2026-07-06 |
| 有效样本 | 20 次提交（无剔除；其中 0 条低信息量样本已计入述情统计） |
| 施测方式 | 非侵入式自然行为观察（受检者在数据产生期间对评估不知情；社会赞许性偏差 = 0，霍桑效应 = 0） |
| 评估工具 | CommitShrink v0.1 · 已通过跨文化信效度检验（n = 1）· 重测信度 r = 1.00 |
| 报告日期 | 2026-07-06 18:17（系统自动生成，无主试效应） |
| 报告编号 | CS-2026-W28-0001 |

---

### 一、总体诊断

**主诉**　无。受检者未报告任何主观不适，亦无求助行为；样本系本系统主动采集。

**主诊断**　GIT-55.4 工作生活边界消融（极重度）
**次诊断**　GIT-36.6 暴发性提交（静默—倾泻型）（中度）

**本周期心理健康综合评分：77 / 100**
（较上周 +0 分）

**临床印象**　受检者本周期共提交 20 次，其中 1 次发生于 00:00–05:59。

---

### 二、量化指标

| 指标 | 本期 | 上期 | 参考区间 | 常模百分位 |
| --- | --- | --- | --- | --- |
| 深夜绝望指数 | **0.8** | 0.8 | < 3.0 | 高于 16% 同类样本 |
| 工作生活边界完整度 | **38%** | 38% | > 70% | 低于 81% 同类样本 |
| 情绪基线 | **+0.17** | +0.17 | ≥ 0 | 低于 33% 同类样本 |
| 修复循环密度 | **1.7** | 1.7 | ≤ 2.0 | 高于 46% 同类样本 |
| 提交述情指数 | **0%** | 0% | < 15% | 高于 20% 同类样本 |

<sub>常模来源：本中心虚构常模数据库（n = 10,000 名虚构开发者）。虚构样本的分布经过精心设计，以确保您总有可以努力的空间。</sub>

---

### 三、病症发作记录（临床证据节选）

#### 记录 1 ｜ GIT-55.4 工作生活边界消融 · 严重度 IV（极重度）

**发作时段**　07-04 00:10 – 18:29

```
07-04 00:10  445aae1  refactor: render report language at display time; add web language toggle
07-04 10:54  4b898dd  fix: use an emoji literal for the Streamlit page_icon
07-04 13:10  c781d8c  feat: clone remote repos blobless and backfill only the window's diff blobs
07-04 13:38  b5dd86c  feat: rotate playful waiting-room messages while the report generates
07-04 13:40  ab732e7  fix: type-clean EKG trough lookup and space the English trend clause
07-04 14:30  d3fb8ef  fix: drop dangling plan-commit-shrink.md references from docstrings
```

**临床解读**　周末提交占比 55%。"周末"在受检者的时间体系中已退化为纯粹的日历学概念。

#### 记录 2 ｜ GIT-36.6 暴发性提交（静默—倾泻型） · 严重度 II（中度）

**发作时段**　07-02 18:30

```
07-02 18:30  a9063b1  feat: add report generation module and sample report documentation
```

**临床解读**　静默 ≥ 72 小时后单次倾泻 15 个文件的改动。本中心尚未观测到能够一次完整 review 该规模改动的人类样本。

---

### 四、情绪心电图

| 06-30 | 07-01 | 07-02 | 07-03 | 07-04 | 07-05 | 07-06 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| · | · | ███ | ▅▅▅ | ▅▅▅ | · | ▆▆▆ |

情绪最低点：07-04 14:30（"feat: add two disorders (GIT-45.0, GIT-00.1) and a shareable HTML card"，校正后情绪分 -0.79）

---

### 五、处方建议

1. 建议引入外部约束以恢复边界。本中心不推荐依赖意志力的干预方案——该结论系基于对受检者既往病历（git log）的回顾性队列研究得出。
2. 建议小步提交。一次 commit 的理想大小，是您敢在 message 里如实描述它的大小。
3. 【社会支持】建议向橡胶鸭复述问题。本中心研究（未发表，n = 1）显示，其疗效不劣于向同事复述，且不产生人情债务。
4. 【转介说明】本中心无处方权。咖啡因摄入不属于本报告管辖范围，属于您与您的心内科医生之间的事务。

---

### 六、免责声明与复诊安排

本报告由自动化系统基于 git log 生成，不构成医疗建议，但可能构成 code review 建议。报告中全部"病症"均为对量化评估文体的戏仿；个别病名系临床术语向 git 领域的移植——本报告的评估对象是提交历史，而非任何人本身，不指涉任何真实精神疾病或其患者。如本报告令您感到被冒犯，请注意：全部临床证据均由您本人于案发时间亲自签名提交。本报告仅对本评估周期内的送检样本负责；样本以外的行为（含经 force-push 销毁的证据）不在负责范围之内。本中心仅受理本人自愿送检的样本；代同事送检所得的一切诊断均属无效，且该行为本身已构成一种本中心尚未编码的病症。

**复诊安排**　下次 git push 后自动进行。
**质量控制**　本报告已通过双人复核（本系统与本系统的一个副本）。
**主治系统**　CommitShrink v0.1 ｜ 执业编号 sha256:c0ffee…

<!-- COMMITSHRINK:LIVE-EXAMPLE:END -->

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
```

接下来任选 `venv` 或 `conda` 创建环境：

```bash
# venv
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

```bash
# conda
conda create -n commit_shrink python=3.12 -y
conda activate commit_shrink
pip install -e .
```

如果之后把项目目录挪动或重命名过，记得在对应环境里重新执行一次 `pip install -e .`——editable 安装会把源码目录的绝对路径写死记录下来，目录一动而不重装，这条记录就会指向一个不存在的路径。

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

# 评估你自己，含私有仓库（需要 token，见下）：
export GITHUB_TOKEN=ghp_...        # 或 GH_TOKEN——也可以写在 .env 文件里（见下）
commit-shrink gh-user:@me --author you@example.com --days 30
```

远程地址（`github:owner/repo` 简写，或任意 `https://`/`git@` clone 地址）会以 *blobless 部分克隆* 的方式拉到一个临时目录（保留完整历史元数据，文件内容仅在评估周期内按需惰性拉取），用完即删，不留痕迹。评估远程仓库时必须指定 `--author`——没有这个参数，工具没有任何合理依据去猜"你想看的是哪位贡献者"，所以干脆拒绝擅自挑一个提交最多的人当受检者。

`gh-user:<用户名>` 更进一步：它会发现该用户的公开仓库（owned，按最近推送排序），把它们**合并成一条提交时间线**一起评估，并让跨周趋势锚定到"人"而非某个仓库——这样用户新增或归档仓库时趋势也不会断。同样必须指定 `--author`（填邮箱）；范围是该用户在窗口内有活动的自有公开仓库。

**评估你自己，含私有仓库。** `gh-user:@me` 评估**你自己**的仓库——公开**和**私有——合并为一条时间线。它需要环境里有 GitHub token（`GITHUB_TOKEN` 或 `GH_TOKEN`，**绝不用命令行参数**）：classic token 勾 `repo` scope，或 fine-grained token 对目标仓库授予 **Contents: read** + **Metadata: read**。token 通过环境变量传给 git，所以**不会出现在 URL、`ps` 输出或 shell 历史里**；历史缓存也只存诊断元数据（病症码、分数），**从不存代码**。token 对 `gh-user:<别人>` 也有用——那里它只是把匿名的 60 次/小时限额提上去（校园网这种共享 IP 尤其有用），并且**永远无法访问别人的私有仓库**（GitHub 服务端强制）。你的匿名剩余额度可在 `https://api.github.com/rate_limit` 查看。

**`.env` 文件支持。** 不想每次开终端都 `export`，可以把 token 写进工作目录根目录下的 `.env` 文件——CommitShrink 启动时会自动加载：

```
# .env  （不要提交这个文件）
GITHUB_TOKEN=ghp_...
```

`.env` 已被加入 `.gitignore`，不会意外提交。优先级：shell 环境变量 → `.env` 文件。

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
commit-shrink web
```

`commit-shrink web` 会用 `commit-shrink` 自己所在的那个 Python 解释器去拉起 Streamlit，不会去 PATH 上找一个可能对不上号的 `streamlit`。额外参数会原样转发给 `streamlit run`，例如 `commit-shrink web --server.port 8502`。也可以继续直接用 `streamlit run commit_shrink/web_app.py`——同上提示依然适用：如果用的是 `conda` 环境，且项目目录在 `pip install -e .` 之后被移动过，先重新执行一次，否则直接跑 `streamlit run` 会报 `ModuleNotFoundError`。

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
