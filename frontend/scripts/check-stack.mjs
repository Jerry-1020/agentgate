import fs from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
const read = path => JSON.parse(fs.readFileSync(new URL(path, new URL('../', import.meta.url)), 'utf8'))
const baseline = read('config/frontend-stack.json')
const manifest = read('package.json')
const lock = read('package-lock.json')
const errors = []
let expectedCount = 0
for (const section of ['dependencies', 'devDependencies']) {
  for (const [name, version] of Object.entries(baseline[section])) {
    expectedCount++
    if (manifest[section]?.[name] !== version) errors.push(name + ': declaration differs from standard ' + version)
  }
  for (const [name, version] of Object.entries(manifest[section])) {
    if (lock.packages[''][section]?.[name] !== version) errors.push(name + ': package-lock declaration differs')
    try {
      const installed = read('node_modules/' + name + '/package.json').version
      if (installed !== lock.packages['node_modules/' + name]?.version) errors.push(name + ': installed version differs from lock')
    } catch { errors.push(name + ': not installed') }
  }
}
const tree = spawnSync('npm', ['ls', '--depth=0', '--json'], { cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 })
if (tree.status !== 0) {
  try { errors.push(...(JSON.parse(tree.stdout).problems ?? ['npm dependency tree validation failed'])) }
  catch { errors.push('npm dependency tree validation failed') }
}
if (errors.length) {
  console.error(errors.join('\n'))
  process.exit(1)
}
console.log(expectedCount + ' standard dependency declarations match; lockfile and installed direct dependencies are consistent.')
