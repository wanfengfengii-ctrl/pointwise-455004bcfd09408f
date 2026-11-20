# 不停采的逐拍交付

站库写入暂缓时，试验员仍要让探头逐拍回值。现场领到的是已经结束的每一拍。夜班可以在采集桥退出后核对原账，明确哪些拍有原读、哪些拍在回值时因槽满而丢失。

## 开班和回值

在原 `AcquisitionBridge.open(shift_id, probe_id, multiplier, offset, limit)` 上增加关键字参数 `overrun=False`。设为 `True` 开不停采班。班次沿用 `AcquisitionBridge(store, capacity)` 的正整数槽容量，开班后模式、容量和定标口径固定。同班同参沿用班次和已存在的会话，异参按原班次冲突处理。

仍由 `bridge.session(shift_id)` 取会话，用 `session.start()` 取得起拍令，再以 `session.finish(token, raw_count)` 交回非负整数计数。拍号从 1 连续推进，同班同时最多一拍在读。错令和非法计数沿用原校验，原活动令保持可办。不停采班即使满槽也可起拍。回值时有槽就保全原读并返回原 `RawReading`，满槽则结束该拍并返回 `None`，既有待接管原读继续占槽。起拍与回值须能在站库提交暂缓期间完成。

## 交付和领取

在原 `ReadingDispatch` 上新增 `deliver_prefix(session)`，给值班交付方接管不停采班。一次取证确定一个真实时点上所有已完结的拍位。从上次正式交付位置的下一拍起，按拍序全部交付到该时点的最后完结拍。没有新完结拍时返回 `None`，不产生空批。尾部只有缺测时也交付。切后回值留待后续批次，在读拍不能提前记为缺测。旧逐件送交及确认不得替代不停采班的批次接管。

成功返回一个字典，字段为 `batch_id`、`shift_id`、`probe_id`、`first_pulse`、`last_pulse` 和 `rows`。批次号为可按号领取的整数，首末拍号均计入。`rows` 是按拍号升序排列的列表。每条有原读的项为 `{'pulse': int, 'raw_count': int, 'concentration': Fraction, 'exceeded': bool}`。沿用班次定标，浓度单位为 μg/m³，浓度严格大于限值才超限。过载项为 `{'pulse': int, 'missing': 'overrun'}`。

同一批的逐拍结果、批次号和交付位置一次提交。只有提交成功才释放本批接管的原读槽。提交失败，批次和新交付位置均不可见，原读继续占槽，值班交付方可重新取证续办。供提交夹具识别的操作名为 `deliver_prefix`。成功续办可纳入此时新增的已完结拍，已保全原读仍按原件交付。

在 `AdmissionService` 上新增 `read_prefix(shift_id)` 和 `read_batch(batch_id)`。前者返回全班已经交付的逐拍结果列表，从第 1 拍开始按拍序排列，已登记但尚未交付的班返回空列表，未知班沿用 `UnknownShiftError`。后者返回相应固定批次及成员，结构与送交结果相同，未知批次报 `LookupError`。两个入口都只读已提交的数据，采集桥退出并重开站库后照常领取。未交付源端状态的断电恢复不在本次范围内。普通班按 README.md 逐拍接纳、停采签班及领报，本次新增的是不停采逐拍交付账。

## 样例与运行

`examples/overload_cases.json` 提供两条各从新班开始的事件脚本。JSON 中的浓度字符串表示 Python 结果中的精确有理数。

- `tail_overrun` 先依次起拍并回值 `completed_counts`，再启动第 5 拍但先不回值，交付 `first_rows`。另开同样的班做失败分支，在首批提交前拒绝本次写入，核对无新账且原槽仍占用。再回传 `active_count`，重试取得 `retry_rows`。随后按 `next_count` 完成第 6 拍并续发 `next_rows`。停源重开时，分别按班和原批次号领取同一账。
- `retained_during_commit` 先完成第 1 拍，再启动第 2 拍。让首批取证后停在提交前，此时回传 `active_count`。第 2 拍回值可完成并保全在空槽。放行首批后只见 `first_rows`，下一次才见 `next_rows`。

保留 `python3 -B check_project.py` 和 `python3 -B -m examples.day_shift` 的原业务。可复用 `tests/fixtures.py` 的提交夹具。更新 `.pointwise-runtime.json`，让 `verify` 执行原回归和本次联合核验，失败返回非零。`demo` 实际采样并展示含尾缺的固定批次和断源重开领取。沿用现有清单版本 1 和 `cli` 类型，`setup` 是命令参数数组的列表，`verify` 与 `demo` 各是一条命令的参数数组。
