# 永客会 Home Assistant 集成

![永客会](custom_components/yongkehui/brand/logo.png)

这是一个面向 HACS 的 Home Assistant 自定义集成，用于登录永客会接口、发现门禁列表，并把门禁暴露为 `lock` 实体。

## 功能

- 通过 Home Assistant UI 输入永客会用户名和密码。
- 登录后从用户 profile 获取 `houseList`，并选择要接入的房屋/小区。
- 选择的 `communityId/custId` 会持久化到配置项中。
- 选定房屋后自动获取门禁列表。
- 每个门禁暴露为一个 Lock Entity。
- Lock Entity 默认名称按 `doorList` 返回的 `name_flagName` 拼接，例如
  `南门_大门门禁`。
- Lock Entity 唯一标识按 `communityId.doorId` 拼接，例如
  `12940241.123456`。
- 调用 `unlock` 时通过永客会 API 开门。
- 开门成功后实体显示为已解锁，5 秒后自动恢复为已上锁。
- 后台每 6 小时调用用户 profile 接口延长登录态。
- 重载或后台刷新发现登录态失效时，使用已保存的账号密码尝试重新登录，并保存更新后的 Cookie。
- 若重新登录需要验证码或密码已变更，支持在原集成上重新认证，保留房屋配置和门禁实体。
- 解锁只调用开门接口；失败后原样重试 1 次。

## 安装

### HACS 自定义仓库

1. 将本目录作为 Git 仓库推送到你自己的仓库。
2. 在 HACS 中添加自定义仓库，类型选择 `Integration`。
3. 安装“永客会”。
4. 重启 Home Assistant。
5. 进入“设置 > 设备与服务 > 添加集成”，搜索“永客会”。

### 手动安装

复制 `custom_components/yongkehui` 到 Home Assistant 配置目录下的 `custom_components/yongkehui`，然后重启 Home Assistant。

## 配置

集成只要求填写：

- 用户名/手机号
- 密码
- 房屋/小区

抓包显示永客会登录请求里的 `password` 不是明文密码，而是 `sg_rsa.encryptLong(sg_rsa.Base64.encode(form.password))` 的结果。集成会在登录前按 App 逻辑动态加密密码；由于 RSA 使用随机填充，同一个明文密码每次生成的 `password` 字段都会变化。登录时会优先从 `https://www.uhomecp.com/web/sassLogin/lib/sg-rsa.js` 拉取并解析 RSA 公钥，解析失败时回退到内置公钥。

抓包中登录失败 `code=20010` 时，永客会会要求图片验证码，成功登录请求会额外带上 `imgCode` 和 `randomToken`。集成会在触发验证码时进入第二步配置表单，自动拉取验证码图片并要求输入图片验证码；如果验证码看不清，可以勾选刷新验证码后提交来重新拉取。验证码是服务端风控行为，即使 App 很久未更新也可能突然启用；因此后台定时刷新优先使用已有 Cookie 调用 profile 接口，仅在登录态失效时尝试一次完整登录。

### 登录失效后恢复

在“设置 > 设备与服务”中点击永客会集成的“重新加载”，集成会先检查已保存的登录态；失效时自动使用已保存的账号密码登录。如果永客会要求验证码或拒绝已保存的密码，Home Assistant 会显示“需要重新认证”。打开该提示后，直接提交可使用原密码重试，也可以输入新密码，再按提示填写验证码。认证成功后自动重新加载原集成，无需删除并重新添加，原房屋配置、门禁实体及相关自动化关联保持不变。

配置时，登录、验证码、profile 这些发生在选择房屋之前的请求不会携带 `communityid` header；只有选择房屋后，门列表和开门请求才会使用持久化的 `communityId`。

## 说明

永客会门禁 API 本身只有“开门”动作，没有真实的远程“上锁”动作。本集成将门禁默认视为已上锁；开门成功后短暂显示为已解锁，并在 5 秒后自动恢复为已上锁。

## 开发验证

使用 Python 3.14 创建虚拟环境，安装 `dev/requirements-test.txt` 后执行 `python -m pytest -q`。回归测试基于 Home Assistant 2026.7.1，使用模拟 API 响应验证重载和重新认证，不会操作真实门禁。
