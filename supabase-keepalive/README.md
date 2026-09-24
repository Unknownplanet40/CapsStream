# Supabase Keepalive for Vercel

This is a tiny standalone Vercel project that sends one **read-only** request to the CapsStream Supabase `media_requests` table once per day. It does not import CapsStream, use the main app's requirements, or write to the table.

> Supabase inactivity pausing is based on a heuristic. Supabase says a few database requests per day typically keep a Free Plan project active, but this daily probe cannot guarantee that the project will never be paused. If you need a firm guarantee, use a Supabase plan without inactivity pausing.

## Deploy this folder by itself

1. Push this repository to a Git provider Vercel can access, or otherwise make the folder available to Vercel.
2. In Vercel, create a new project and select this repository.
3. In the project setup/settings, set **Root Directory** to `supabase-keepalive`. Do not choose the CapsStream repository root. This keeps the deployment limited to this folder and its standard-library Python function.
4. Add these environment variables for **Production**:
   - `SUPABASE_URL`: your Supabase project URL, e.g. `https://your-project-ref.supabase.co`.
   - `SUPABASE_ANON_KEY`: the project's anon/publishable key. Do **not** use a service-role or secret key.
   - `CRON_SECRET`: a long random secret used to authenticate the scheduled endpoint. Generate one locally, for example with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
5. Deploy (and redeploy after changing environment variables). `vercel.json` schedules `/api/keepalive` once daily at 04:17 UTC. On Vercel Hobby, the invocation can happen at any time within the scheduled hour.

The anon key needs `SELECT` access to `public.media_requests`; the schema in `../docs/supabase_schema.sql` includes an anon read policy. The endpoint only selects one `id` and does not expose row data.

## Verify it

After deployment, open **Vercel → Project → Cron Jobs** and confirm `/api/keepalive` is listed. Check its invocation under the Vercel function/runtime logs. Vercel sends `Authorization: Bearer <CRON_SECRET>` to Cron invocations automatically when `CRON_SECRET` is configured.

You can also test the deployed route manually. It should return `401` without the secret and a small JSON success response with it:

```sh
curl -i -H "Authorization: Bearer YOUR_CRON_SECRET" https://YOUR_PROJECT.vercel.app/api/keepalive
```

Do not post or commit the secret. A successful manual request confirms configuration and Supabase connectivity; Vercel's scheduled invocation confirms the recurring trigger is working.

## Local tests

No third-party packages are needed:

```sh
cd supabase-keepalive
python -m unittest discover -s tests -v
```
