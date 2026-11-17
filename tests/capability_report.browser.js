async page => {
  await page.goto('http://127.0.0.1:8096/capability-report');
  await page.getByRole('button', {name:'Run capability report'}).waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.getElementById('start').disabled);
  await page.locator('#models input').evaluateAll(nodes=>nodes.forEach((n,i)=>n.checked=i===0));
  await page.route('**/v1/decision',route=>{const id=Object.keys(route.request().postDataJSON().schema).find(id=>id.endsWith('_choice'));return route.fulfill({status:429,contentType:'application/json',body:JSON.stringify({error:'Fixture partial failure',complete:false,results:[{decision:{[id]:true},fields:{[id]:{value:true,noul:.9}}}]})})});
  await page.getByRole('button',{name:'Run capability report'}).click();
  await page.waitForFunction(()=>!document.getElementById('start').disabled);
  const partial=await page.locator('#summary').textContent();
  if(!partial.includes('7 error')||!partial.includes('1 match'))throw Error('Partial fields lost: '+partial);
  await page.unroute('**/v1/decision');
  const originalJudge=JSON.parse(await page.locator('#evidence').textContent()).judge;
  let checks=0,calls=0;
  await page.route('**/health',async route=>{
    checks++;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({selected_backend:checks===1?originalJudge:'remote:changed-fixture'})});
  });
  await page.route('**/v1/decision',route=>{calls++;return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({results:[{decision:{choice:true},fields:{choice:{noul:.9}}}]})})});
  await page.getByRole('button',{name:'Run capability report'}).click();
  await page.waitForFunction(()=>!document.getElementById('start').disabled);
  const changed=await page.locator('#summary').textContent();
  const evidence=await page.locator('#evidence').textContent();
  if(!changed.includes('8 error')||!evidence.includes('Judge changed during request')||calls!==1)throw Error('Judge change was not excluded');
  console.log(JSON.stringify({partial,changed,calls}));
  await page.unroute('**/health');await page.unroute('**/v1/decision');
}
