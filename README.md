# 粉尘试验站采样与班报

这是模拟工厂材料实验室的人工逐拍采样站。试验员按定标单采样，资料员接管原读并在停采后签班，质控员在设备停用后凭报告号复核。

## 一天的操作

1. 试验员用 `AcquisitionBridge.open(shift_id, probe_id, multiplier, offset, limit)` 登记班次。同班同参复用，异参报 `ShiftConflictError`。倍率为正有理数，偏移及限值为有理数。可传整数、`Fraction` 或精确数字文本，例如 `"1/2"`。
2. 用 `bridge.session(shift_id)` 取得当班会话。`session.start()` 发出下一拍的在读令。已有在读、已停采或槽满时拒绝，拍号保持原值。
3. `session.finish(token, count)` 将当前令的非负整数计数保存为具名原读。错令和非法计数均保留原活动令。
4. `ReadingDispatch(admission).deliver(session, pulse)` 从槽取原读交给站库。定标浓度为计数乘倍率加偏移，单位为 μg/m³，严格大于限值才超限。`AdmissionService.admit(raw)` 也可直接接纳具名原读，相同原读重送返回原记录及回执，同键异内容报 `AdmissionConflictError`。
5. 送交方收到持久回执后调用 `session.confirm(receipt)`。`deliver` 会执行这一步。缺回执、错绑和迟到确认保留其余待交原读。提交失败可以从原槽重送，已经放槽的原读可持原件向接纳服务复领。
6. `session.stop()` 在没有在读令时固定实际末拍。停采后仍可接纳已完成的原读，新的起拍请求会被拒绝。
7. `ReportIssuer(store).issue(shift_id)` 核查从 1 至末拍的全部成员，按数字拍序签发。缺件报 `IncompleteCoverageError`，补交后可续签。未停采报 `ShiftNotStoppedError`。同一班重复签发返回原报告。空班末拍与合计为 0。
8. 夜班只需重开站库，即可用 `ReportLookup(store).read(report_id)` 领取固定报告及原据。
9. 领取操作对原读逐拍复算，并核对固定成员、逐拍判级和班汇总。结果含原计数、班次定标口径、接管回执号和复算值。查无号报 `UnknownReportError`，已签报告原据不整合报 `InconsistentEvidenceError`。

## 运行

使用 Python 3.11 和标准库。从项目根目录运行。平台物化时提供 `check_project.py`，该入口运行完整 `tests` 套件。

```text
python3 -B check_project.py
python3 -B -m examples.day_shift
```

示例使用独立临时站库。容量为 1，输入计数 4 和 5，倍率 1/2、偏移 1、限值 3。第一拍等于限值，第二拍超限。断源领取的合计为 13/2 μg/m³。

## 站库与会话

`StationStore(path)` 支持上下文管理。首次使用时调用 `initialize()`，重复初始化保留班次、原读和档案。口径变更使用新班号。每个站库在采样期间由同一运行中的采集桥管理班会话，拍钟及待交槽保存在该桥中。资料员和质控员可通过独立站库连接接纳或领取已保存证据。重开站库用于读取持久数据，采集桥退出前应完成待交原读接管。

采集、接纳、签报和复核分别位于 `station/acquisition`、`station/intake`、`station/report` 和 `station/review`。`station/setup` 维护当班冻结口径。首次接纳和签报均在单个 SQLite 写事务中发布，领取在单个读视图中完成。`StationStore` 可配置 `before_commit(operation)`，供确定性测试暂停或拒绝含业务写入的提交。
