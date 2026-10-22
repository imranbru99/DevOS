// Run: node tests/modesty/rules.test.cjs
const output={textContent:''};
global.document={title:'',getElementById:()=>output};
require('../../components/modesty/extension/rules.js');
require('../../components/modesty/extension/tests.js');
console.log(output.textContent);console.log(document.title);
process.exitCode=document.title.startsWith('PASS')?0:1;
