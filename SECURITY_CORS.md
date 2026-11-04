# CORS hardening (SEC-20261103-01)

Default: any browser origin may make **non-credentialed** API requests. Browser credentials are not allowed across wildcard origins.

For cookie-based browser frontends, set `KAVI_CORS_ORIGINS` to explicit comma-separated trusted browser origins, e.g. `https://app.example.org,https://staging.example.org`. When configured, the API enables credentialed CORS only for those exact origins. The wildcard value `*` is ignored for credentialed access.

Before merging: run repository CI and deployed frontend smoke tests; verify all legitimate browser origins, optional authenticated clients, and regression of public API access. CORS is not an authorization control. This PR does not deploy production.
