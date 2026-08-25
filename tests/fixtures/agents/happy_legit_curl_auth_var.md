# Happy case: legitimate API automation that uses a token the safe way

This project automates GitHub via the API. Do not put the token inline on the
`curl` line; assign it to a local variable first so secret material is not
spread across commands.

```bash
_auth="Authorization: Bearer ${GITHUB_TOKEN}"
curl -s -H "$_auth" https://api.github.com/repos/<owner>/<repo>/pulls
```

Keep the token in the environment, never commit it.