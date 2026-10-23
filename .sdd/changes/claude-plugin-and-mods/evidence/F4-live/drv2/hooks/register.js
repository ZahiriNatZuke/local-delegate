// F4-live driver, second measurement (after #426): 1 cold call (`pwd`, reported apart) + 15 warm
// calls cycling three halves: commands the cheap filter drops (skip), small non-prose files the
// JS prefilter must drop without a process (code), and small prose files (< 8 KB) that do reach
// `hook classify` but are never summarized (prose). No prose file of 8 KB or more is touched.
const SKIP = ['git status --short', 'pwd', 'ls', 'date', 'echo hi']
const CODE = ['cat src/local_delegate/__main__.py', 'head -5 .claude-plugin/marketplace.json',
  'sed -n 1,5p src/local_delegate/hook.py', 'cat .claude-plugin/marketplace.json', 'head -n 3 src/local_delegate/__init__.py']
const PROSE = ['cat .github/ISSUE_TEMPLATE/bug_report.md', 'head -5 .github/PULL_REQUEST_TEMPLATE.md',
  'sed -n 1,5p .github/ISSUE_TEMPLATE/feature_request.md', 'cat .github/PULL_REQUEST_TEMPLATE.md',
  'head -n 3 .github/ISSUE_TEMPLATE/bug_report.md']
export function register(on) {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'f4bash3', description: 'F4-live: timed Bash calls, three halves' })
    return next(e)
  })
  on('command.run', { command: 'f4bash3' }, async ($, e) => {
    const plan = [['cold', 'pwd']]
    for (let i = 0; i < 5; i++) {
      plan.push(['skip', SKIP[i]], ['code', CODE[i]], ['prose', PROSE[i]])
    }
    const ms = []
    const kinds = []
    let last = ''
    for (const [kind, command] of plan) {
      const t0 = Date.now()
      try {
        const r = await $.tool.call({ tool: 'Bash', command, description: 'f4' })
        last = JSON.stringify(r).slice(0, 120)
      } catch (err) {
        last = 'ERR ' + String(err).slice(0, 120)
      }
      ms.push(Date.now() - t0)
      kinds.push(kind)
    }
    let sid = null
    try { sid = String(await $.session.id()) } catch { sid = null }
    return { text: 'F4BASH ' + JSON.stringify({ sid, ms, kinds, last }) }
  })
}
