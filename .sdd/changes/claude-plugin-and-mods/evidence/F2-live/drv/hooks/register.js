// F2-live driver: fires real tool calls without a model turn (same method as T0's t0-driver).
// /f2bash N   -> N sequential Bash calls (`echo f2`), each timed with Date.now() around $.tool.call
// /f2mcp PATH -> one call to mcp__local-delegate__local_summarize through every PreToolUse hook
export function register(on) {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'f2bash', description: 'F2-live: timed Bash calls' })
    await $.command.register({ name: 'f2mcp', description: 'F2-live: one local-delegate tool call' })
    return next(e)
  })
  on('command.run', { command: 'f2bash' }, async ($, e) => {
    const n = Math.max(1, parseInt((e.args || '1').trim(), 10) || 1)
    const ms = []
    let last = ''
    for (let i = 0; i < n; i++) {
      const t0 = Date.now()
      try {
        const r = await $.tool.call({ tool: 'Bash', command: 'echo f2', description: 'f2' })
        last = JSON.stringify(r).slice(0, 160)
      } catch (err) {
        last = 'ERR ' + String(err).slice(0, 160)
      }
      ms.push(Date.now() - t0)
    }
    return { text: 'F2BASH ' + JSON.stringify({ ms, last }) }
  })
  on('command.run', { command: 'f2mcp' }, async ($, e) => {
    const path = (e.args || '').trim()
    try {
      const r = await $.tool.call({ tool: 'mcp__local-delegate__local_summarize', path, max_words: 20 })
      return { text: 'F2MCP OK ' + JSON.stringify(r).slice(0, 400) }
    } catch (err) {
      return { text: 'F2MCP ERR ' + String(err).slice(0, 400) }
    }
  })
}
