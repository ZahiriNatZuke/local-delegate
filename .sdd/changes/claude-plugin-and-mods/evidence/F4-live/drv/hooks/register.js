// F4-live driver (copy of F2-live's, adapted): fires real Bash calls without a model turn.
// /f4bash -> 1 cold call (`pwd`, reported apart) + 10 warm calls alternating a command that passes
// the read mod's cheap filter (goes to `hook classify`) and one that does not. Each call is timed
// with Date.now() around $.tool.call. Prints the session id for the heartbeat check.
const PASS = ['cat LICENSE', 'head -5 .gitignore', 'sed -n 1,5p LICENSE', 'cat .gitignore', 'head -n 3 LICENSE']
const SKIP = ['git status --short', 'pwd', 'ls', 'git log -1 --oneline', 'date']
export function register(on) {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'f4bash', description: 'F4-live: timed Bash calls' })
    return next(e)
  })
  on('command.run', { command: 'f4bash' }, async ($, e) => {
    const plan = [['cold', 'pwd']]
    for (let i = 0; i < 5; i++) {
      plan.push(['pass', PASS[i]])
      plan.push(['skip', SKIP[i]])
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
