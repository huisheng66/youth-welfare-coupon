// T21 前端 dev server 启动器（Windows 非 ASCII 工作区兼容）。
//
// 为什么不直接让 Playwright 以项目根为 cwd 启动 vite：
// - 部分环境（Git Bash 会话 / 特定 codepage）向子进程显式传非 ASCII cwd
//   会让 CreateProcess 失败（spawn ENOENT）；
// - 而项目根被 subst 映射为 ASCII 盘符时，vite 的模块解析会在
//   盘符路径与 realpath 之间错位，transform 全部回落为原始文件。
//
// 解法：Playwright 在 ASCII 临时目录下用 node 启动本脚本；脚本内部
// chdir 到项目根的真实路径（node 内部为 UTF-16，不经命令行转换），
// 再以「继承式 cwd」+ 纯 ASCII 相对路径 spawn vite —— vite 以真实
// 项目根为 root，命令行里不出现非 ASCII 字符。
//
// 用法：node run-frontend.mjs <frontendRoot> [port]
import { spawn } from 'node:child_process'
import { realpathSync } from 'node:fs'
import path from 'node:path'

const frontendRootArg = process.argv[2]
if (!frontendRootArg) {
  console.error('usage: node run-frontend.mjs <frontendRoot> [port]')
  process.exit(2)
}
const port = process.argv[3] || process.env.E2E_FRONT_PORT || '5199'

// 展开链接/短路径后进入真实项目根（subst 盘会让 vite 的模块解析与
// realpath 视图错位，transform 全部回落为原始文件，因此必须用真实路径）
const frontendRoot = realpathSync(path.resolve(frontendRootArg))
process.chdir(frontendRoot)
console.log(`[run-frontend] cwd=${process.cwd()} port=${port}`)

const child = spawn(
  process.execPath,
  ['node_modules/vite/bin/vite.js', '--port', port],
  {
    // 不传 cwd：继承 chdir 后的进程工作目录；vite 以 cwd 为 root
    stdio: 'inherit',
    env: process.env,
  },
)

function killTree() {
  if (process.platform === 'win32') {
    spawn('taskkill', ['/T', '/F', '/PID', String(child.pid)], { stdio: 'ignore' })
  } else {
    child.kill('SIGTERM')
  }
}
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(sig, () => {
    killTree()
    process.exit(0)
  })
}
process.on('exit', () => {
  if (!child.killed && child.exitCode === null) killTree()
})

child.on('exit', (code) => process.exit(code ?? 0))
child.on('error', (err) => {
  console.error('[run-frontend] spawn failed:', err)
  process.exit(1)
})
