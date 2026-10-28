// 사용: node cap.js <real|illus> <all|t1,t2,...> <출력폴더> [index.html 경로]
// all  → 30fps 전 프레임 JPEG,  t1,t2 → 해당 초의 정지 화면 확인용
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const [mode, what, out, page = path.join(__dirname, 'index.html')] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  await p.goto('file://' + path.resolve(page) + '?mode=' + mode);
  await p.waitForFunction(() => window.READY === true, null, { timeout: 90000 });
  const total = await p.evaluate(() => window.TOTAL);
  console.log('TOTAL', total);
  if (what !== 'all') {
    for (const t of what.split(',').map(Number)) {
      await p.evaluate(x => window.setTime(x), t);
      await p.screenshot({ path: `${out}/st_${mode}_${t}.jpg`, type: 'jpeg', quality: 70 });
    }
  } else {
    const fps = 30, n = Math.ceil(total * fps);
    for (let i = 0; i < n; i++) {
      await p.evaluate(x => window.setTime(x), i / fps);
      await p.screenshot({ path: `${out}/${String(i).padStart(5, '0')}.jpg`, type: 'jpeg', quality: 90 });
      if (i % 300 === 0) console.log('frame', i, '/', n);
    }
    console.log('DONE', n);
  }
  await b.close();
})();
