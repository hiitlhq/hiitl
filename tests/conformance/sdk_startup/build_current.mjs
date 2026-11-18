// A child must execute this tree's source, including a mutation, not a saved dist.
// Build in a private directory: other test workers and worktrees keep their files.
import {cpSync, mkdirSync, readdirSync, realpathSync, symlinkSync} from 'node:fs';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';

export function buildCurrent(root, destination, packages = ['core', 'sdk']) {
  for (const name of packages) {
    const source = join(root, 'typescript/packages', name);
    const target = join(destination, 'typescript/packages', name);
    mkdirSync(target, {recursive: true});
    for (const item of ['src', 'package.json', 'tsconfig.json', 'tsconfig.build.json']) {
      cpSync(join(source, item), join(target, item), {recursive: true});
    }
    const dependencies = join(target, 'node_modules');
    mkdirSync(dependencies);
    for (const entry of readdirSync(join(source, 'node_modules'))) {
      if (entry === '@hiitl') {
        mkdirSync(join(dependencies, entry));
        for (const member of readdirSync(join(source, 'node_modules', entry))) {
          symlinkSync(member === 'core'
            ? join(destination, 'typescript/packages/core')
            : realpathSync(join(source, 'node_modules', entry, member)), join(dependencies, entry, member));
        }
      } else {
        symlinkSync(realpathSync(join(source, 'node_modules', entry)), join(dependencies, entry));
      }
    }
    execFileSync(process.execPath, [join(source, 'node_modules/typescript/bin/tsc'), '-p', 'tsconfig.build.json'],
      {cwd: target, encoding: 'utf8', stdio: 'pipe'});
  }
  return destination;
}
