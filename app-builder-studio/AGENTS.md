<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->
- All verification logic lives in the FastAPI backend (../backend). The frontend talks to it only through src/lib/api.ts; every mutating call returns a server-masked session view.
- Routes: / (verification history), /verify (step-by-step flow, session id in ?s=), /case/$id (result page). All use ssr:false because they need the browser (geolocation, localStorage) and the local API.
- Design: minimal. One typeface (Schibsted Grotesk), white surfaces, black as the only accent; green/amber/red only for verification status. Tokens are in src/styles.css. Avoid decorative styling (uppercase tracked labels, serif display type, textures).
