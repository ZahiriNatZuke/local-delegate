"""Builds case 19: a ~30 KB pricing page with the markup noise of a real marketing site.

Invented data (the same table as case 15, more rows). Deterministic: no randomness, no clock.
Run: python build_noisy_page.py   (writes 19-pricing-page-noisy-en.html next to this file)
"""

from __future__ import annotations

from pathlib import Path

ROWS = [
    ("Custom domains", "1–5", "1–3 per region", "Addresses of your own for previews and docs sites."),
    ("Storage per workspace", "50 GB", "2 TB", "Caches, artifacts and container layers."),
    ("API requests per minute", "600", "6 000", "Counted per access token."),
    ("Concurrent pipelines", "4", "40", "Pipelines running at the same time."),
    ("Audit log retention", "30 days", "365 days", "How long the audit trail is kept."),
    ("Build artifact retention", "14 days", "180 days", "How long build outputs are kept."),
    ("Environments per project", "3", "25", "Deployment targets with their own secrets."),
    ("Scheduled pipelines", "10", "500", "Pipelines started by a timer."),
    ("Single sign-on (SAML)", "—", "Included", "Sign in with your identity provider."),
    ("Self-hosted runner", "—", "Available on request", "Run jobs on your own machines."),
    ("Uptime commitment", "99.5%", "99.95%", "Monthly availability of the control plane."),
    ("Support", "Email, 2 business days", "24/7 phone and email", "How to reach us."),
]

FEATURES = [
    ("Pipelines as code", "One file in the repository describes build, test and release."),
    ("Shared caches", "Dependencies are restored between branches and purged on demand."),
    ("Scoped secrets", "Secrets are encrypted and visible only to the environment that owns them."),
    ("Merge gates", "A change lands only when the checks you choose are green."),
    ("Preview sites", "Every merge request gets an address where reviewers can try it."),
    ("Command line client", "The same commands on Linux, macOS and Windows."),
    ("Templates", "Reuse a pipeline across projects and update it in one place."),
    ("Visual editor", "See the stages as a graph and edit them without leaving the browser."),
    ("Notifications", "Chat, mail and webhooks, with rules per branch."),
    ("Insights", "Duration, queue time and flaky tests, per pipeline and per week."),
]

FAQ = [
    ("Can I try Enterprise before I decide?", "Yes. Ask sales for a trial workspace; it stays active for three weeks."),
    ("Do you offer discounts?", "Registered charities, schools and open source projects can apply for a reduced rate."),
    ("How do I pay?", "Standard is paid by card. Enterprise can also be paid by bank transfer against an invoice."),
    ("Where is my data stored?", "You choose the region when you create the workspace; logs and artifacts stay there."),
    ("What happens if I cancel?", "The workspace becomes read-only at the end of the period and can be exported for a month."),
    ("Can I change plan later?", "Yes, at the end of any billing period, without recreating pipelines."),
    ("Is there a setup fee?", "No. Enterprise onboarding is part of the contract."),
    ("Do you sign a data processing agreement?", "Yes, on both plans; the template is on the security page."),
]

NAV = ["Product", "Pipelines", "Runners", "Integrations", "Documentation", "Changelog", "Pricing", "Customers", "Blog", "Contact"]
FOOT = ["Terms of service", "Privacy", "Security", "System status", "Careers", "Press kit", "Brand", "Sitemap", "Cookie settings", "Accessibility"]

ICON = (
    '<svg class="h-5 w-5 flex-none text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">'
    '<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5'
    'a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd"/></svg>'
)
CELL = "px-6 py-4 text-sm leading-6 text-slate-700 dark:text-slate-200 whitespace-nowrap border-b border-slate-200/70"


def page() -> str:
    out: list[str] = []
    add = out.append
    add('<!doctype html>\n<html lang="en" class="h-full scroll-smooth antialiased">\n<head>')
    add('<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">')
    add("<title>Plans and pricing | Tidewater CI</title>")
    add('<meta name="description" content="Compare the Standard and Enterprise plans of Tidewater CI.">')
    add('<meta property="og:title" content="Plans and pricing | Tidewater CI">')
    add('<meta property="og:type" content="website">')
    for sheet in ("base", "layout", "pricing", "fonts"):
        add(f'<link rel="stylesheet" href="/assets/{sheet}.3f9a1c.css">')
    add("<style>:root{--brand:#0b6e99;--ink:#0f172a;--paper:#fff}.compare th{position:sticky;top:0}"
        ".tip{border-bottom:1px dotted currentColor;cursor:help}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden}</style>")
    add('</head>\n<body class="flex min-h-full flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">')
    add('<a class="sr-only focus:not-sr-only" href="#main">Skip to content</a>')
    add('<header class="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur dark:bg-slate-950/90">')
    add('<div class="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 lg:px-8">')
    add('<a class="text-lg font-semibold tracking-tight" href="/">Tidewater CI</a>\n<nav aria-label="Main"><ul class="hidden gap-x-8 lg:flex">')
    for name in NAV:
        cur = ' aria-current="page"' if name == "Pricing" else ""
        add(f'<li><a class="text-sm font-medium leading-6 text-slate-700 hover:text-slate-900 dark:text-slate-200" href="/{name.lower()}"{cur}>{name}</a></li>')
    add("</ul></nav>\n</div>\n</header>")
    add('<main id="main" class="flex-auto">')
    add('<section class="mx-auto max-w-7xl px-6 py-24 sm:py-32 lg:px-8"><div class="mx-auto max-w-4xl text-center">')
    add('<h1 class="text-4xl font-bold tracking-tight sm:text-6xl">Plans and pricing</h1>')
    add('<p class="mt-6 text-lg leading-8 text-slate-600 dark:text-slate-300">Tidewater CI builds, tests and ships your code from the same pipeline file, on our runners or on yours.</p>')
    add('<p class="mt-4 text-sm leading-6 text-slate-500">Prices are loaded at runtime; contact sales for a quote.</p>')
    add('<div id="price-cards" class="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-2" data-source="/api/prices" data-state="loading">')
    for plan in ("Standard", "Enterprise"):
        add(f'<div class="rounded-3xl p-8 ring-1 ring-slate-200 xl:p-10" data-plan="{plan.lower()}"><h2 class="text-lg font-semibold leading-8">{plan}</h2>'
            '<p class="mt-6 flex items-baseline gap-x-1"><span class="text-4xl font-bold tracking-tight" data-price>…</span>'
            '<span class="text-sm font-semibold leading-6 text-slate-600" data-period></span></p>'
            f'<a class="mt-6 block rounded-md px-3 py-2 text-center text-sm font-semibold leading-6 ring-1 ring-inset ring-sky-200" href="/contact?plan={plan.lower()}">Contact sales</a></div>')
    add("</div></div></section>")
    add('<section class="bg-slate-50 py-24 dark:bg-slate-900"><div class="mx-auto max-w-7xl px-6 lg:px-8">')
    add('<h2 class="text-3xl font-bold tracking-tight">What every plan includes</h2>\n<dl class="mt-10 grid grid-cols-1 gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">')
    for title, text in FEATURES:
        add(f'<div class="relative pl-9"><dt class="inline font-semibold text-slate-900 dark:text-white">{ICON}<span>{title}.</span></dt> '
            f'<dd class="inline text-slate-600 dark:text-slate-300">{text}</dd></div>')
    add("</dl></div></section>")
    add('<section class="py-24"><div class="mx-auto max-w-7xl px-6 lg:px-8">')
    add('<h2 class="text-3xl font-bold tracking-tight">Compare plans</h2>')
    add('<p class="mt-4 text-base leading-7 text-slate-600">The table lists the limits that differ between the two plans. A dash means the feature is not part of the plan.</p>')
    add('<div class="mt-10 overflow-x-auto"><table class="compare min-w-full border-separate border-spacing-0 text-left">')
    add('<thead><tr>' + "".join(
        f'<th scope="col" class="bg-white/75 px-6 py-3.5 text-sm font-semibold text-slate-900 backdrop-blur">{h}</th>'
        for h in ("Feature", "Standard", "Enterprise")) + "</tr></thead>\n<tbody>")
    for label, std, ent, tip in ROWS:
        add(f'<tr class="even:bg-slate-50 dark:even:bg-slate-900"><td class="{CELL} font-medium text-slate-900">'
            f'<span class="tip" title="{tip}" data-tip="{tip}">{label}</span></td>'
            f'<td class="{CELL}"><span class="inline-flex items-center gap-x-1.5">{std}</span></td>'
            f'<td class="{CELL}"><span class="inline-flex items-center gap-x-1.5">{ent}</span></td></tr>')
    add("</tbody></table></div>")
    add('<p class="mt-6 text-sm leading-6 text-slate-500">Limits are counted per workspace unless the row says otherwise.</p>')
    add("</div></section>")
    add('<section class="bg-slate-50 py-24 dark:bg-slate-900"><div class="mx-auto max-w-4xl px-6 lg:px-8">')
    add('<h2 class="text-3xl font-bold tracking-tight">Frequently asked questions</h2><dl class="mt-10 space-y-6 divide-y divide-slate-900/10">')
    for q, a in FAQ:
        add(f'<div class="pt-6"><dt><button type="button" class="flex w-full items-start justify-between text-left" aria-expanded="false">'
            f'<span class="text-base font-semibold leading-7">{q}</span><span class="ml-6 flex h-7 items-center">{ICON}</span></button></dt>'
            f'<dd class="mt-2 pr-12"><p class="text-base leading-7 text-slate-600 dark:text-slate-300">{a}</p></dd></div>')
    add("</dl></div></section>\n</main>")
    add('<footer class="border-t border-slate-200 bg-white dark:bg-slate-950"><div class="mx-auto max-w-7xl px-6 py-12 lg:px-8">')
    add('<p class="text-sm leading-6 text-slate-600">All plans include unlimited projects.</p><ul class="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-5">')
    for name in FOOT:
        add(f'<li><a class="text-sm leading-6 text-slate-600 hover:text-slate-900" href="/{name.lower().replace(" ", "-")}">{name}</a></li>')
    add('</ul><p class="mt-8 text-xs leading-5 text-slate-500">&copy; Tidewater CI. All product names are fictional and used for illustration.</p></div></footer>')
    faq_ld = ",".join(
        '{"@type":"Question","name":"%s","acceptedAnswer":{"@type":"Answer","text":"%s"}}' % (q, a) for q, a in FAQ
    )
    add('<script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[%s]}</script>' % faq_ld)
    add('<script>window.__TW__={"page":"pricing","flags":{"annualToggle":true,"regionPicker":false},"build":"3f9a1c"};</script>')
    add('<script src="/assets/prices.3f9a1c.js" defer></script>\n</body>\n</html>')
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    target = Path(__file__).with_name("19-pricing-page-noisy-en.html")
    target.write_text(page(), encoding="utf-8", newline="\n")
    print(target.name, len(target.read_bytes()), "bytes")
