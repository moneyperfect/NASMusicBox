# music.nasbuild.dev 接入

网站已部署预览：https://nas-music-box.social-bass-8514.chatgpt.site

托管端已绑定 `music.nasbuild.dev`，当前等待 DNS 验证。`nasbuild.dev` 解析在 Cloudflare，需要在该域名的 DNS 设置添加以下记录，保留博客现有记录。

| 类型 | 名称（Cloudflare 区域内） | 内容 |
| --- | --- | --- |
| CNAME | music | custom-domains.chatgpt.site |
| TXT | _openai-site-verification.music | openai-site-verification=jaoK9jLi84Ncv4C6iniKay1ph3O3TZL5gMW4Y3Dyj5M |
| TXT | _cf-custom-hostname.music | 2f307331-c75f-4b3b-8c6e-cace3e6ba90e |

CNAME 使用“仅 DNS”（灰云），让托管平台完成 HTTPS 证书验证。记录生效后需核对托管端域名状态和 https://music.nasbuild.dev/ 的实际响应；绑定请求成功不等于域名已经可访问。

项目 ID：`appgprj_6acd0b1d03e48191814ec2ead59ab286`。目前预览仅拥有者可访问。公开发行时需公开网站访问权限，并在安装包上传且链接验证成功后启用 `release.json` 的正式下载。
