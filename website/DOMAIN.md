# music.nasbuild.dev 接入

网站已公开：https://nas-music-box.social-bass-8514.chatgpt.site

1. 登录 https://dash.cloudflare.com/ ，选择 `nasbuild.dev`。
2. 进入 **DNS → Records（记录）→ Add record（添加记录）**。
3. 按下表添加三条记录，TTL 使用 Auto（自动）。名称只填写表格中的相对名称，Cloudflare 会补齐 `.nasbuild.dev`。
4. CNAME 的 Proxy status（代理状态）设为 **DNS only（仅 DNS，灰色云朵）**。TXT 记录没有代理选项。
5. 如果已经存在名为 `music` 的 A、AAAA 或 CNAME，只调整该子域名的冲突记录。保留 `@`、`www` 和其他博客记录。
6. 保存后等待 DNS 与 HTTPS 证书验证，稍后访问 https://music.nasbuild.dev/ 。托管平台已提交域名绑定，会自动验证；不用修改网页代码或重新上传安装包。

托管端已绑定 `music.nasbuild.dev`，当前等待 DNS 验证。`nasbuild.dev` 解析在 Cloudflare，需要在该域名的 DNS 设置添加以下记录，保留博客现有记录。

| 类型 | 名称（Cloudflare 区域内） | 内容 |
| --- | --- | --- |
| CNAME | music | custom-domains.chatgpt.site |
| TXT | _openai-site-verification.music | openai-site-verification=jaoK9jLi84Ncv4C6iniKay1ph3O3TZL5gMW4Y3Dyj5M |
| TXT | _cf-custom-hostname.music | 2f307331-c75f-4b3b-8c6e-cace3e6ba90e |

CNAME 使用“仅 DNS”（灰云），让托管平台完成 HTTPS 证书验证。记录生效后需核对托管端域名状态和 https://music.nasbuild.dev/ 的实际响应；绑定请求成功不等于域名已经可访问。

项目 ID：`appgprj_6acd0b1d03e48191814ec2ead59ab286`。网站已设为公开，1.7.0 体验版安装包与便携版已上传并核对 SHA-256，正式下载按钮已启用。

如果尚未生效，先确认三条记录的名称、内容和灰云状态；不要改动博客主域名的解析。等待后仍有问题，可让我检查域名和 HTTPS 验证状态。

Cloudflare 操作说明：https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/
