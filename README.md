# 4seas 房间看板

Linux 使用三个服务：`web`（Next.js 页面和 API）、`collector`（Python 采集）、`db`（PostgreSQL）。

## 启动

在有蓝牙和 BlueZ 服务的 Linux 主机上运行：

```bash
docker compose up -d --build
```

打开 http://localhost:3000 展示体验页面。在手环上开启心率广播，
进入 http://localhost:3000/manage，找到设备并点击「开始采集」。
启用状态和数据保存在 PostgreSQL 中；断线后采集服务自动重试。
新发现的蓝牙设备不会自动连接。已指定的 AirGradient 首次接入自动启用；
之后会保留页面上的暂停/启用设置。

蓝牙和 AirGradient 不需要 `.env`；Eight Sleep 只需邮箱和密码（见下文）。
数据库名和用户名为 `postgres`，密码为 `docker`，已固定在
`compose.yaml` 中。网页仅监听本机 `127.0.0.1:3000`，数据库不暴露宿主机端口。
采集容器通过挂载宿主机 D-Bus 使用蓝牙，不需要浏览器蓝牙权限。

部分双模手环（包括本次测试的小米手环）会让 BlueZ 优先尝试经典蓝牙，导致
能扫描到但连接超时。采集代码会为这类心率设备指定 BLE；宿主机 BlueZ 需在
`/etc/bluetooth/main.conf` 的 `[General]` 中设置 `Experimental = true`，
然后执行 `sudo systemctl restart bluetooth`。本机已完成该设置。
这用于开放 `PreferredBearer` 接口，不需要修改项目 `.env`。

```bash
docker compose logs -f collector  # 查看采集状态
docker compose down              # 停止服务，保留数据卷
```

`db/init.sql` 在空数据卷首次启动时初始化表。后续修改已有表需要显式执行相应 SQL；
重建镜像不会修改现有数据库结构。不要使用 `down -v`，除非确实要删除所有采集数据。

## macOS / Apple Silicon 部署

Mac 上由 Docker 运行 Next.js 和 PostgreSQL，采集器原生运行在项目 .venv 中，
通过 CoreBluetooth 采集手环、Bonjour 解析环境设备，同时采集 Eight Sleep。
这种方式只保留一个采集器和一份心跳，不需要额外转发 API、令牌或 .env 配置。
Mac 的内置蓝牙不能通过 Linux 的 D-Bus socket 挂载方式提供给 Docker Desktop。

准备运行中的 Docker Desktop（Compose 2.24.4+）和原生 Python 3.11+（建议 3.13），
在项目目录执行：

```bash
python3 tools/start_macos.py
```

脚本创建/复用本项目 .venv，安装当前平台依赖，启动 Docker 中的 db 和 web，
再安装本机采集器为当前用户的登录服务；已有容器采集器会先停止，避免重复采集。
Mac 本机打开 http://localhost:3000；同一局域网可通过 http://Mac的IP:3000 访问，
管理页为 /manage。
关闭终端或断开 SSH 不影响采集；登录 Mac 后采集器自动启动。
同时在 Docker Desktop 设置中启用登录时启动 Docker。
同一项目启动第二个本机采集器会被进程锁拦截。

首次使用请允许“4seas 采集器”的蓝牙和本地网络请求。
若曾拒绝，在「系统设置 → 隐私与安全性」的「蓝牙」和「本地网络」中分别开启。
应用声明这两项权限用途，授权仍需用户在 Mac 上确认。设备扫描按标准心率服务过滤。
日志位于 .runtime/collector.log；登录服务为 local.fourseas.collector。
安装器使用项目的 Python 解释器封装本地应用，不增加 .env 配置项。
本机测试部署使用项目 .runtime/python 中的独立 Python 3.13。
macOS 使用 CoreBluetooth UUID 标识手环，而不是 Linux 蓝牙 MAC 地址；
迁移后请在管理页重新启用扫描到的手环，旧记录不会自动与另一标识合并。
0 心率和无效接触读数仍不入库，断线自动重连。

Mac 配置使用 compose.macos.yaml，移除 D-Bus 挂载并只向本机开放 PG 5432。
数据库名、用户名 postgres，密码 docker；.env 仍只有 Eight Sleep 邮箱和密码。
使用 Docker Compose 解析 .env 后把凭据直接传给本机进程，不执行 .env 内容。

Dockerfile 和 Compose 不固定 amd64；在 M 系列 Mac 上原生构建 linux/arm64，
在 x86 Linux 上构建 linux/amd64。Node/Python/PostgreSQL 使用官方多架构镜像，
npm 和 pip 依赖在目标架构内安装。迁移时不要复制 .venv、node_modules 或 .next。
可用以下命令查看运行的镜像架构：

```bash
docker image inspect localhost/fourseas-web:latest --format '{{.Architecture}}'
docker image inspect postgres:17-alpine --format '{{.Architecture}}'
```

独立蓝牙诊断（先退出采集器，避免同时连接同一手环）：

```bash
.venv/bin/python tools/collect_heart_rate.py --name "Xiaomi Smart Band" --seconds 30
```

平台依据：[Bleak macOS 后端](https://bleak.readthedocs.io/en/latest/backends/macos.html)、
[Docker 多架构构建](https://docs.docker.com/build/building/multi-platform/)。

## Mac 新增手环

1. 在手环中开启「心率广播」或「心率共享」，佩戴后放在运行服务的 MacBook 附近。
   手环需要广播标准 BLE Heart Rate 服务；普通蓝牙可见并不等于支持心率采集。
2. 保持 Mac 蓝牙开启，且「系统设置 → 隐私与安全性 → 蓝牙」已允许「4seas 采集器」。
   这是应用级授权，添加另一只手环不需要重新安装或修改 .env，也不用手填 UUID。
3. 打开体验页面，通常等待约 10–20 秒，在「选择手环」中选中设备，输入名字并开始体验。
   选中开始后自动启用该手环的采集，不需要先去管理页点「开始采集」。
   多只同名手环用名称后面的标识末四位区分；不确定对应关系时可以逐只开启心率广播确认。
4. 其他体验者在各自客户端选择另外的空闲手环。手环连接到 MacBook，不是打开网页的 iPad/手机。
   已占用手环不会出现在其他体验者的可选列表中；结束体验后可以再次选择。

当前 Xiaomi Smart Band 10 的广播已实测无需在 macOS 蓝牙设置里手动配对。
其他设备如果要求认证，由 macOS 在访问对应服务时提示。
如果 20 秒后仍未出现，先在 /manage 查看设备列表：确认心率广播已开启、设备在 Mac 附近，
必要时断开另一台正在采集心率的电脑或应用，再关闭并重开心率广播。
不需要删除手环与手机的日常绑定，也不要清空蓝牙权限或系统蓝牙配置。

扫描约每 10 秒一轮；临时扫描失败只重试发现流程，不会连带断开已有手环。
每只手环独立连接和重连，连接等待 30 秒。收到 0 心率只更新设备在场时间，不存为样本。
超过 60 秒没有广播或有效连接通知的设备不再供新体验选择，服务端也会校验。
同时可连接的实际数量取决于蓝牙硬件和手环，当前没有人为设置单手环上限。

## 房间看板与体验记录

页面复用 CTD-space 的房间看板设计：深绿 / 暖白主题、环境与床侧指标卡片、
真实采样时间轴，以及独立的手环心率区。主题选择会在浏览器本地保存。
体验者首页按视口高度布局，电脑与 iPad 横屏并排、竖屏上下排列；不展示采集状态、
连接错误或技术说明。手环和环境读数无效、过期或设备离线时显示「—」；床读数保留最后有效值及其接收时间。
操作管理、原始数据、设备错误与体验历史统一在 /manage 页面，右上角图标可进入。

每个客户端负责一位体验者：输入名字并选择手环后开始体验，结束后弹出记录二维码。
二维码内容只有本次体验 UUID，不包含网址。可以截图或点「保存图片」；以后在
「历史记录」（/records）按名字、UUID 和录入时间找到记录，点击查看详情。IP 或主机名变化不影响 UUID 本身。
二维码生成在本地浏览器完成，不经过第三方服务。

多位体验者可同时使用不同客户端和手环；同一手环不能同时绑定两次进行中的体验。
手环心率只归给对应体验者，房间环境和床的快照存储一次并关联到所有同时进行的体验。
心率 0、无效接触和无效读数不入库。管理页可以查看分页原始记录并重新显示已结束体验的二维码。
客户端标识保存在各自浏览器中，刷新恢复本机体验，不同步其他客户端的当前体验。
关闭浏览器或重启服务不会自动结束体验；开始请求重试不会为同一客户端创建第二次体验。
同一浏览器的标签页共享客户端标识；不同浏览器或设备是独立客户端。

体验按钮控制数据归属，数据源自身的开始 / 暂停在管理页的「数据源与采集记录」中。
没有进行中的体验时继续采集，但新样本不关联体验者。旧数据不会自动分配到新体验。

归属区间为开始时间（包含）至结束时间（不包含），按样本的接收时间匹配；
结束后才写入的排队样本仍归入原体验。开始、结束和采集写入使用同一事务锁，
防止同时操作造成交叉归档。Eight Sleep 按快照接收时间归档，快照内的旧睡眠
记录不代表本次体验者的实时身体数据；历史日表仍按原账号和日期保存。

已有数据库升级（保留所有原数据）：

```bash
docker compose up -d db
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d postgres < db/005_parallel_experiences.sql
docker compose up -d --build
```

已有数据库应已具备 004 的体验表；此次升级执行 005，不能在多人体验期间重跑 004 的旧单人约束。
空数据卷会按顺序自动执行全部迁移。没有新增服务、端口或 `.env` 配置项。

```sql
-- 每次体验及样本数量
SELECT e.id, e.name, e.started_at, e.ended_at, count(s.sample_id) AS samples
FROM experiences e LEFT JOIN experience_samples s ON s.experience_id = e.id
GROUP BY e.id ORDER BY e.started_at DESC;

-- 某次体验的完整原始数据（将 UUID 换为体验编号）
SELECT s.source_id, s.recorded_at, s.value, s.metadata
FROM experience_samples x JOIN samples s ON s.id=x.sample_id
WHERE x.experience_id = '替换为体验 UUID'
ORDER BY s.recorded_at, s.id;
```

## AirGradient 完整采集

已接入序列号 `e83dc16b9dcc`，通过宿主机 Avahi 的 mDNS 服务解析
`airgradient_e83dc16b9dcc.local`，不写死 IP。宿主机需要运行 Avahi；
容器复用已有 D-Bus 挂载，无需增加服务、端口或 `.env` 配置。
连接失败后会重新解析地址并重试。

每秒请求一次 `/measures/current`，每个成功响应作为一条 `samples` 记录：

- `source_id`：`airgradient:e83dc16b9dcc`
- `recorded_at`：实际接收时间（UTC）
- `metadata.measurements`：完整 JSON，包括全部测量、字符串、空值、
  设备状态以及固件未来新增的字段；当前设备返回 29 个字段。
- `metadata.address`：本次访问的 IP 地址
- `value`：CO₂ 数值，供默认预览；CO₂ 缺失时为 NULL，其他字段仍完整保存。

1 Hz 是请求频率，不代表设备内部传感器每秒都会更新。数值重复时仍保存本次
快照；超时/断线时不生成记录，不追补漏采数据。请求串行执行，慢请求不会堆积。
HTTP 连接/读取超时和 mDNS 解析等待上限均为 30 秒；超时后等待 5 秒重试。
页面可切换全部数值指标的曲线，并展开查看完整 JSON。

从旧版本升级时，先执行一次兼容现有数据的迁移，再启动服务：

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d postgres < db/002_airgradient.sql
docker compose up -d --build
```

查询示例：

```sql
SELECT recorded_at,
       metadata->'measurements' AS measurements
FROM samples
WHERE source_id = 'airgradient:e83dc16b9dcc'
ORDER BY recorded_at DESC
LIMIT 10;
```

## 目录

```text
compose.yaml
compose.macos.yaml  Mac 原生采集 + ARM64 Docker 配置
web/           Next.js 前端、API 和 Dockerfile
collector/     采集模块、数据库写入、依赖和 Dockerfile
db/            数据库初始化
tools/         Mac 启动入口和独立蓝牙诊断脚本
data/          之前采集的本地 CSV，不参与镜像构建
tests/         采集协议测试
vendor/eight_sleep/  用户指定的上游仓库（固定版本，仅供参考，不装 Home Assistant）
```

## Eight Sleep 完整采集

已拉取 [lukas-clarke/eight_sleep](https://github.com/lukas-clarke/eight_sleep)，
固定提交 `1f5d84e3171385ac3b50d41ce76164f4c4cd7647`。采集器依据其 pyEight
协议实现只读适配，保留 MIT 许可证于 `collector/LICENSE.eight_sleep`。
另外对照了 [eightctl](https://github.com/steipete/eightctl/tree/main/internal/client)
和 [Eight Sleep SDK](https://github.com/mergd/apk2sdk/tree/main/packages/eight-sleep)
的外设、底座预设和音频查询；实际测试可用的附加端点也纳入采集。

根目录 `.env` 只有两项，已有值无需重填：

```dotenv
EIGHT_EMAIL=你的登录邮箱
EIGHT_PASSWORD=你的登录密码
```

密码包含 `$` 或 `#` 时可用单引号包住整个值，避免 Compose 插值。
`.env` 不进入 Git 和 Docker 构建上下文，仅给 collector 注入这两项环境变量；
认证令牌仅保存在内存中，日志与数据库过滤密码、令牌等认证字段。

已有数据库首次升级执行：

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d postgres < db/003_eight_sleep.sql
docker compose up -d --build
```

以后更改账号密码，执行 `docker compose up -d collector`，Compose 会重建采集容器。
新数据卷会自动执行迁移。服务仍是原来的三个，不额外增加容器或配置项。

每 10 秒发起一轮采集，以轮次开始时间计时，同一轮最多并发 8 个只读请求。
每个请求超时仍为 30 秒；慢请求会跳过已错过的轮次，不重叠启动或补发请求。
401 自动重新登录一次，429 尊重服务端 Retry-After，
其他连接错误退避重试；页面暂停同时停止后续轮询和历史补采。

采集范围（以账号权限及接口成功返回为准）：

- 账号资料、家庭、全部设备及外设、用户与床侧关联、固件、Wi-Fi、在线、水箱与维护状态。
- 温控档位、智能温控、全部温控设备（包括枕头）、当前及下一份计划、闹钟。
- 底座状态和预设、音频播放器状态、曲目目录、分类及收藏。
- 所有可访问用户的睡眠评分、全部睡眠会话、分期、心率、HRV、呼吸率、
  温度时序、时长和服务端返回的其他字段。无数据时保存空结果，不生成模拟数值。

每轮完整响应在 `samples.metadata.responses`，按接口命名；未知字段、数组、
字符串和空值均保留。`metadata.errors` 记录各接口的 HTTP 状态及已知错误类型，
单个附加接口失败不丢弃其他成功结果。`metadata.measurements` 只是当前账号的
看板预览，其他用户及完整时序仍在原始 JSON 中。

体验页优先显示当前可用的床侧指标，最多六项：左右床温、左右背部/腿部角度等；没有数据的睡眠指标不占用卡片。左右床温只在当前床在线且温度
可用时提取，按上游 pyEight 的最近档位查表换算为摄氏度，以 ≈ 标注；
原始档位、换算温度及完整响应均保存到 PG。温控关闭不代表设备离线。
睡眠记录中的 tempBedC 保持独立，不以当前床温填充。

床面板逐项保留最后一次有效读数：等待、断线、超时、空值不会清空已有数值，
新的有效值才更新对应字段；角度的 0 是有效值，心率的 0 仍被忽略。
最后有效值及各字段的接收时间保存在快照的 metadata.display，刷新页面和重启
采集器后均可恢复。原始 metadata.measurements 仅包含本轮读数，不把旧值
伪装成本轮采集数据；首次尚无数据的指标不显示占位横线。

**404 不代表没有底座或播放器。** 例如 `PodOffline` 表示云端报告 Pod 离线，
`NoPairedPod` 表示用户与 Pod 的关联不可用，页面会区分显示并持续重试。
设备的云端缓存可能仍可读取，不能据此认定实时在线。只调用认证与查询接口，
不会通过改变床侧、配对、床角度或播放状态来尝试修复读取。

历史按 30 天窗口回填至账号创建日期，窗口间至少等待 10 秒；空月份不会提前
终止回填，失败不会推进游标。`eight_sleep_days` 按数据源、用户、日期去重，
保存完整日记录及全部会话/时序；近几天在每轮同步时更新，`eight_sleep_sync`
记录可恢复进度。账号没有睡眠记录时，历史行数为 0。

```sql
-- 每轮完整响应与接口错误
SELECT recorded_at, metadata->'responses', metadata->'errors'
FROM samples
WHERE source_id IN (SELECT id FROM sources WHERE kind='eight_sleep')
ORDER BY recorded_at DESC LIMIT 1;

-- 去重后的历史日数据
SELECT user_id, day, data FROM eight_sleep_days ORDER BY day DESC LIMIT 10;
```

看板地址仍为 http://localhost:3000，选择「Eight Sleep」即可查看。
云端睡眠分期、在床状态和生理指标可能延迟；页面展示接收时间与睡眠数据日期。

## 接入其他采集

1. 在 `collector/sources/` 新增模块，实现 `async def run(store)`。
2. 用 `store.discover(id, name, kind, metric, unit, metadata)` 注册一个数据源。
3. 通过 `await store.enabled(kind)` 判断用户是否启用了该源，用
   `await store.write(id, value, recorded_at, metadata)` 写入数值和 UTC 时间戳。
4. 将模块加入 `collector/sources/__init__.py` 的 `COLLECTORS`，重建采集镜像。

单指标来源直接使用 `value`；多指标设备可以像 AirGradient 一样，每次保存一个
完整快照到 `metadata.measurements`，由页面选择展示指标。接触状态、原始包等
附加信息也放在 `metadata`。无需为每种采集另建 API、表或容器。
模块退出时会被重启；模块内部负责连接、读取与断线处理，并响应任务取消。

心率来源按系统设备标识区分（Linux 地址 / macOS UUID）。如果设备变更地址，会作为新来源出现，需要重新启用。
页面每 2 秒刷新；上报频率按实际接收时间戳计算，不受页面刷新间隔影响。

手环摘下后可能继续广播 `06 00`：原始接触标记仍为 true，但心率为 0。
采集器直接跳过 0 值、空值和设备明确报告未接触的无效通知，不新增样本，
也不增加样本计数；同时更新为等待有效心率；展示页读数变为「—」，具体状态仅在管理页显示。
连接保持订阅，有效心率恢复后继续写入；有效样本仍保留原始接触标记和数据包。
旧版本已保存的 0 / NULL 历史记录保留，页面不会把它们当作有效心率。
暂停、断线或超过 10 秒无新数据时，当前测量状态显示「状态未知」。
有效读数的接触状态标为「设备报告接触」，不能保证实际佩戴。

## 本地检查

所有开发命令在 `agent-runner` 中执行：

```bash
distrobox enter agent-runner -- .venv/bin/python -m pip install -r collector/requirements.txt
distrobox enter agent-runner -- .venv/bin/python -m unittest discover -s tests
distrobox enter agent-runner -- node --test tests/test-heart-rate.mjs
distrobox enter agent-runner -- sh -lc 'cd web && npm ci && npm run build'
```

体验归档和 API 集成测试使用自动创建 / 删除的独立测试数据库，不写入真实采集表：

```bash
# 在 agent-runner 中，将地址替换为 compose db 容器的内部 IP
TEST_PG_HOST=172.18.0.2 .venv/bin/python -m unittest discover -s tests -p test_experience_store.py
```

覆盖时间边界、延迟写入、零心率过滤、并发开始、重复结束、名字校验、
体验之间的数据隔离、数据源筛选及分页。不指定 TEST_PG_HOST 时跳过这两项集成测试。

独立蓝牙诊断：

```bash
distrobox enter agent-runner -- .venv/bin/python tools/collect_heart_rate.py \
  --name "Xiaomi Smart Band 10" --seconds 30
```

## 当前测试部署

运行机器为 MacBook；页面、PostgreSQL、蓝牙、环境及 Eight Sleep 采集均在 Mac 上运行。
开发机仅用于开发，旧数据卷和 .runtime/pre-mac-migration.dump 作为迁移备份保留。
项目位于 Mac 的 ~/chao-test，原生采集器日志位于 .runtime/collector.log。
局域网可访问 http://madeMacBook-Pro.local:3000，当前 IP 为 http://10.97.215.51:3000。
.local 依赖客户端支持 Bonjour/mDNS；mac.lan 需路由器配置本地 DNS 后才可用。
切换网络时 IP 可能变化；体验 UUID 和数据库记录仍保留。

Docker Desktop 和采集器在用户登录后启动；Mac 需要保持开机、唤醒且用户已登录。
数据库仅监听 Mac 的 127.0.0.1:5432。部署下载用的开发机代理已移除。

## 空气指标参考值

体验页的空气卡片右上角显示小字参考；不按实时读数做合格判定或告警。
PM2.5 / PM10 的「日均」明确指 24 小时平均值，实时读数仍保留在主读数区。
VOC / NOx 显示传感器指数基线，不能换算为健康安全限值；PM1.0 不编造独立阈值。

| 指标 | 卡片参考 | 依据与含义 |
| --- | --- | --- |
| 温度 | 舒适 20–26°C | 一般室内舒适参考；概括冬夏范围，随季节、衣着和个人感受变化，不是统一睡眠温度标准。[加拿大职业热舒适说明](https://www.canada.ca/en/employment-social-development/services/health-safety/reports/thermal-stress-work-place.html) |
| 相对湿度 | 参考 30–50% | [EPA 室内空气建议](https://www.epa.gov/indoor-air-quality-iaq/care-your-air-guide-indoor-air-quality) |
| CO₂ | 通风 <800 ppm | 良好通风参考，不是毒性界限。[AirGradient 指标解释](https://www.airgradient.com/documentation/kb/airgradient-dashboard-measurement-and-interpretation) |
| PM2.5 | 日均 ≤15 µg/m³ | [WHO 2021 指导表](https://www.ncbi.nlm.nih.gov/books/NBK574582/table/fm-ch1.tab1/) |
| PM10 | 日均 ≤45 µg/m³ | 同上，24 小时平均浓度 |
| PM1.0 | 暂无独立标准 | 暂无广泛采用的独立指导值，参考变化趋势。[AirGradient](https://www.airgradient.com/documentation/kb/airgradient-dashboard-measurement-and-interpretation) |
| VOC 指数 | 基线 100 | 相对历史环境的指数。[Sensirion VOC/NOx 说明](https://sensirion.com/en/media/documents/ACD82D45/6294DFC0/Info_Note_Integration_VOC_NOx_Sensor.pdf) |
| NOx 指数 | 基线 1 | 同上，不是 NO₂ 浓度 |

空气卡片保留各项最后一次有效读数，仅由新的有效数值覆盖；缺失字段、断连和采集服务暂时离线不会清空读数。从未收到数据的项目不显示。展示缓存随真实快照持久化，刷新页面或重启采集器后恢复；原始测量与历史曲线仍保留实际采样，不把旧值补写成新测量。

历史记录页 /records 按体验开始时间倒序列出记录（每页 100 条），展示按时间正序生成的序号、名字、完整 UUID 与北京时间录入时间；点击记录进入详情，返回列表时保留原分页位置。

## Git 仓库

主仓库：`git@github.com:vincent-jobs/4seas-show-temp.git`。

```sh
git clone --recurse-submodules git@github.com:vincent-jobs/4seas-show-temp.git
cd 4seas-show-temp
cp .env.example .env
```

上游参考代码以子模块固定版本，已有克隆可运行 `git submodule update --init` 获取。
账号密码、采集数据、数据库备份与运行目录不进入版本库；部署前在 .env 中填写 Eight Sleep 账号。
