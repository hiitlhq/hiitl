const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');
const root=process.argv[2],ts=createRequire(path.join(root,'typescript/packages/sdk/package.json'))('typescript');
const names=new Set(JSON.parse(process.argv[3]));const directory=path.join(root,'typescript/packages/sdk/src');const sites=[],publicExports=[];
function files(folder){return fs.readdirSync(folder,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(folder,e.name)):e.name.endsWith('.ts')?[path.join(folder,e.name)]:[]);}
for(const file of files(directory)){
 const text=fs.readFileSync(file,'utf8'),source=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true);const relative=path.relative(root,file);
 function owner(node){let names=[];for(let p=node.parent;p;p=p.parent){if(ts.isConstructorDeclaration(p))names.unshift('constructor');else if((ts.isMethodDeclaration(p)||ts.isFunctionDeclaration(p)||ts.isClassDeclaration(p)||ts.isVariableDeclaration(p))&&p.name)names.unshift(p.name.getText(source));}return names.join('.');}
 function visit(node){
  if(ts.isCallExpression(node)&&names.has(node.expression.getText(source))){sites.push({language:'typescript',path:relative,line:source.getLineAndCharacterOfPosition(node.getStart()).line+1,owner:owner(node),guard:node.expression.getText(source),arguments:node.arguments.map(n=>n.getText(source))});}
  if(path.basename(file)==='index.ts'&&ts.isExportDeclaration(node)&&node.exportClause&&ts.isNamedExports(node.exportClause)&&!node.isTypeOnly){for(const e of node.exportClause.elements)if(!e.isTypeOnly)publicExports.push({language:'typescript',name:e.name.text,module:node.moduleSpecifier?.text??null});}
  ts.forEachChild(node,visit);
 }visit(source);
}
process.stdout.write(JSON.stringify({sites,exports:publicExports}));
