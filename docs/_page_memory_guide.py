# @generated-adjacent: prose module for docs/build_docs.py (imported, not standalone)
"""Standalone extraction guide for the memory module.

Kept in its own module because it is the one page written for readers who do not
use DAI Nexus at all — they want the memory component and nothing else.
"""

from __future__ import annotations


def render(f: dict, code, table, callout, esc, stat_grid) -> str:
    api_rows = [
        ["<code>add(text, category, title, tags, importance)</code>",
         "Ghi một quan sát. Tự redact secret, tự gắn tag, tự chống trùng bằng hash nội dung. "
         "Trả <code>{id, duplicate, tags}</code>."],
        ["<code>memory_index(query, limit)</code>",
         "Lớp 1 — chỉ tiêu đề + điểm. Rẻ nhất, dùng để quét trước."],
        ["<code>memory_search(query, limit)</code>",
         "Lớp 2 — BM25 fuse với importance/recency bằng RRF. Đây là hàm bạn gọi 90% thời gian."],
        ["<code>memory_get(id)</code>", "Lớp 3 — toàn bộ bản ghi."],
        ["<code>list_all(category, limit)</code>", "Duyệt theo category, mới nhất trước."],
        ["<code>delete(id)</code>", "Xoá mềm (đánh dấu <code>archived</code>), không mất dữ liệu."],
        ["<code>count()</code> · <code>stats()</code>", "Đếm bản ghi sống · thống kê theo category + dung lượng."],
        ["<code>gc(max_obs)</code>", "Lưu trữ bớt bản ghi giá trị thấp khi vượt ngưỡng."],
    ]

    config_rows = [
        ["<code>DB_PATH</code>", "hằng số đầu file", "Nơi đặt file .db. Đổi sang <code>.myagent/memory.db</code> "
         "hoặc bất kỳ đường dẫn nào hợp với cấu trúc của bạn."],
        [f"<code>{'</code> · <code>'.join(f['mem_env'])}</code>", "biến môi trường",
         "Namespace project · ngưỡng GC · tắt redaction (không khuyến nghị)."],
        ["<code>CATEGORY_WEIGHTS</code>", f"{len(f['mem_weights'])} mục",
         "Cái gì đáng giữ lại khi GC. Đổi tên category cho khớp domain của bạn — "
         "ví dụ game studio có thể thêm <code>art-direction</code>, <code>balance</code>."],
        ["<code>AUTO_TAG_PATTERNS</code>", f"{len(f['mem_tags'])} domain",
         "Regex → tag. Thêm domain của bạn; bỏ cái không dùng (ví dụ bỏ <code>game</code> nếu làm fintech)."],
        ["<code>REDACT_PATTERNS</code>", f"{f['mem_redact_count']} mẫu",
         "Bổ sung định dạng secret riêng của tổ chức (mã nhân viên, khoá nội bộ, số hợp đồng)."],
        [f"<code>RRF_K</code> = {f['mem_rrf_k']}", "hằng số",
         "Hằng số làm mượt của RRF. Giảm → thứ hạng đầu bảng có trọng số cao hơn. "
         "Không có lý do đo được thì đừng đổi."],
    ]

    return f'''
<section class="hero compact">
  <span class="tag">TRANG ĐỘC LẬP · BÓC TÁCH ĐỂ DÙNG NƠI KHÁC</span>
  <h1>Memory — <span class="accent">một file, mang đi đâu cũng chạy</span></h1>
  <p class="lead">
    Trang này viết cho người <strong>không dùng DAI Nexus</strong> mà chỉ muốn lấy phần trí nhớ.
    Toàn bộ nằm trong <strong>một file Python {f["memory_loc"]} dòng</strong>, chỉ dùng thư viện chuẩn:
    không pip install, không service, không API key, không cần phần còn lại của repo này.
  </p>
  {stat_grid([("1", "file cần copy"), ("0", "dependency"),
              (str(len(f["mem_api"])), "hàm public"), (str(len(f["mem_cli"])), "lệnh CLI")], 4)}
</section>

<h2><span class="num">01</span> Cài trong 60 giây</h2>
<div class="code-block"><div class="code-head"><span class="file">3 bước</span></div><pre><code># 1. Chép đúng một file vào project của bạn
cp scripts/lite/memory.py  your-project/tools/memory.py

# 2. Kiểm tra SQLite của bạn có FTS5 (gần như luôn có, nhưng cứ kiểm tra)
python -c "import sqlite3; sqlite3.connect(':memory:').execute(
  'CREATE VIRTUAL TABLE t USING fts5(x)'); print('FTS5 OK')"

# 3. Dùng ngay — DB tự tạo ở lần ghi đầu tiên
python tools/memory.py add "Chọn Postgres thay vì Mongo vì cần transaction" --category decisions --importance 9
python tools/memory.py search "database"</code></pre></div>
{callout("tip", "Không có bước 4",
 "Không có file config bắt buộc, không có migration, không có server. "
 "Schema tự tạo lúc kết nối đầu tiên (<code>CREATE TABLE IF NOT EXISTS</code>), nên việc "
 "&quot;cài đặt&quot; chỉ là chép file.")}

<h2><span class="num">02</span> Bên trong có gì (đủ để bạn tin nó)</h2>
<p>Một bảng thật + một bảng FTS5 ảo + {len(f["mem_triggers"])} trigger giữ đồng bộ + {f["mem_index_count"]} index.
Hết. Không có tầng trừu tượng nào khác:</p>
{code("scripts/lite/memory.py", r"CREATE TABLE IF NOT EXISTS observations", 12, "bảng chính")}
<p>Điểm đáng chú ý là FTS được cập nhật bằng <strong>trigger</strong> ({", ".join(f"<code>{t}</code>" for t in f["mem_triggers"])}),
không phải rebuild index mỗi lần tìm. Đây là khác biệt giữa tìm kiếm tức thì và tìm kiếm chậm dần theo dữ liệu:</p>
{code("scripts/lite/memory.py", r"CREATE TRIGGER IF NOT EXISTS obs_ai", 14, "đồng bộ FTS")}

<h3>Ba lớp truy xuất</h3>
{table(["Lớp", "Hàm", "Trả về", "Chi phí"], [
  ["1", "<code>memory_index</code>", "tiêu đề + điểm", "~15 token/kết quả"],
  ["2", "<code>memory_search</code>", "tóm tắt 200 ký tự, đã fuse xếp hạng", "~60 token/kết quả"],
  ["3", "<code>memory_get</code>", "bản ghi đầy đủ", "~200 token/kết quả"],
])}
<p>Nguyên tắc: nạp lớp rẻ trước, chỉ xuống lớp đắt khi thật cần. Nếu bạn nhồi cả kho nhớ vào context
thì không cần thư viện nào cả — cái khó là <em>không</em> làm thế.</p>

<h3>Xếp hạng: BM25 fuse với importance/recency</h3>
<p>Hai bảng xếp hạng độc lập được hợp nhất bằng Reciprocal Rank Fusion — thứ gì đứng cao ở
<em>cả hai</em> sẽ thắng, nên một ghi chú vừa đúng từ khoá vừa quan trọng sẽ vượt lên trên
một ghi chú chỉ trùng từ khoá:</p>
{code("scripts/lite/memory.py", r"^def rrf_merge", 14)}

<h2><span class="num">03</span> Bốn cách gắn vào hệ của bạn</h2>

<h3>A. Dùng như thư viện Python</h3>
<div class="code-block"><div class="code-head"><span class="file">cách dùng phổ biến nhất</span></div><pre><code>from tools.memory import MemoryDB

db = MemoryDB("var/agent-memory.db")          # đường dẫn tuỳ bạn

db.add("Rate limit API là 100 req/phút cho gói free",
       category="architecture", importance=8)

for hit in db.memory_search("rate limit", limit=3):
    print(hit["id"], hit["rrf"], hit["summary"])</code></pre></div>
{table(["Hàm", "Việc"], api_rows)}

<h3>B. Dùng như CLI — từ bất kỳ ngôn ngữ nào</h3>
<p>Không phải project nào cũng viết bằng Python. CLI in ra stdout nên gọi được từ Node, Go, Rust, shell script, cron:</p>
<div class="code-block"><div class="code-head"><span class="file">{len(f["mem_cli"])} lệnh: {", ".join(f["mem_cli"])}</span></div><pre><code># từ Node.js
execFileSync("python", ["tools/memory.py", "search", query, "--format", "json"])

# từ shell / CI
python tools/memory.py add "$(git log -1 --pretty=%s)" --category git-activity
python tools/memory.py stats</code></pre></div>
<p><code>search --format json</code> trả JSON để parse; mặc định là dạng gọn cho người đọc.</p>

<h3>C. Expose cho agent qua MCP</h3>
<p>Nếu agent của bạn nói giao thức MCP, bọc hai hàm là đủ — không cần SDK:</p>
{code("mcp/server.py", r"^def tool_memory_search", 8, "toàn bộ adapter cho search")}

<h3>D. Móc vào vòng đời của một agent framework khác</h3>
<p>Trí nhớ chỉ có giá trị khi được nạp <em>và</em> được lưu tự động. Hai móc, không hơn:</p>
{table(["Móc", "Khi nào", "Làm gì"], [
  ["<strong>Boot / bắt đầu phiên</strong>", "trước khi xử lý yêu cầu",
   "<code>memory_search(&lt;từ khoá của yêu cầu&gt;, limit=3)</code> → nhét vào system prompt, "
   "<strong>có trần token</strong> (ví dụ ≤500) và cắt bớt nếu vượt"],
  ["<strong>Turn close / kết thúc lượt</strong>", "sau khi hoàn thành",
   "<code>add(\"REQ: … | DONE: … | OPEN: …\", category=\"session\")</code>; quyết định quan trọng "
   "ghi riêng với <code>category=\"decisions\", importance=8+</code>"],
])}
{callout("warn", "Cái bẫy ai cũng dính",
 "Nạp memory mà không đặt trần token thì sau vài tuần, phần trí nhớ sẽ nuốt hết context window "
 "và bóp chết chính công việc mà nó định giúp. Trần cứng + cắt bớt là bắt buộc, không phải tuỳ chọn.")}

<h2><span class="num">04</span> Sửa cho hợp cấu trúc của bạn</h2>
<p>Tất cả điểm cấu hình nằm ở đầu file, dạng hằng số — không có lớp config nào:</p>
{table(["Điểm", "Hiện tại", "Đổi khi nào"], config_rows)}
<p class="muted small">Tag domain mặc định: {", ".join(f"<code>{t}</code>" for t in f["mem_tags"])}.</p>

<h3>GC — cái gì sống sót khi kho đầy</h3>
<p>Điểm = trọng số category (50%) + độ mới (50%). Bản ghi <code>pinned</code> không bao giờ bị dọn,
và &quot;dọn&quot; nghĩa là <em>đánh dấu archived</em>, không phải DELETE:</p>
{code("scripts/lite/memory.py", r"^    def gc", 12)}
<p>Thứ tự ưu tiên hiện tại: {" · ".join(f"<code>{k}</code>={v}" for k, v in f["mem_weights"][:5])} …
Một quyết định kiến trúc sống lâu hơn nhiều so với một ghi chú vặt — hãy chỉnh bảng này theo
thứ tự giá trị của <em>domain bạn</em>, đó là chỗ đáng sửa nhất.</p>

<h2><span class="num">05</span> Đừng đổi mấy thứ này</h2>
{table(["Thành phần", "Vì sao giữ nguyên"], [
  ["<code>PRAGMA journal_mode=WAL</code>",
   "Cho phép nhiều tiến trình đọc trong khi một tiến trình ghi. Bỏ WAL là mở đường cho "
   "<code>SQLITE_BUSY</code> ngay khi bạn chạy hai worker."],
  ["Trigger đồng bộ FTS", "Thay bằng rebuild index thủ công thì tìm kiếm chậm dần theo dữ liệu, "
   "và sẽ có lúc index lệch với bảng thật."],
  ["<code>UNIQUE(content_hash, project_root)</code>",
   "Chống trùng ở tầng dữ liệu. Agent sẽ ghi lại cùng một điều nhiều lần — đó là bản chất, không phải lỗi."],
  ["Redact <em>trước khi</em> ghi",
   "Redact lúc đọc là quá muộn: secret đã nằm trên đĩa. Thứ tự này là điểm mấu chốt."],
  ["Xoá mềm (<code>archived</code>)",
   "Agent xoá nhầm thì phục hồi được. Một dòng SQL đổi lại, thay vì mất vĩnh viễn."],
])}

<h2><span class="num">06</span> Giới hạn đã biết — nói trước để khỏi bất ngờ</h2>
<ul class="rules">
  <li><strong>Chưa có vector search.</strong> Xếp hạng hiện tại là BM25 (khớp từ) fuse importance/recency.
  Tìm theo <em>ý nghĩa</em> (hỏi &quot;chậm&quot; ra được ghi chú viết &quot;latency&quot;) thì cần thêm nhánh embedding —
  <code>rrf_merge</code> đã viết sẵn để nhận nguồn xếp hạng thứ hai, cắm vào là chạy.</li>
  <li><strong>FTS5 phải có trong bản SQLite của bạn.</strong> Python chính thức gần như luôn có; bản build lạ thì kiểm tra bằng lệnh ở mục 01.</li>
  <li><strong>Đừng đặt file .db trên ổ mạng.</strong> Khoá SQLite qua SMB/NFS là nguồn hỏng dữ liệu kinh điển.</li>
  <li><strong>Namespace theo project</strong> lấy từ git remote hoặc tên thư mục. Nhiều project chung một file .db thì
  phải set <code>{f["mem_env"][2] if len(f["mem_env"]) > 2 else "PROJECT_ID"}</code> rõ ràng, nếu không chúng lẫn vào nhau.</li>
  <li><strong>Redaction là lưới, không phải bảo đảm.</strong> Nó bắt {f["mem_redact_count"]} định dạng phổ biến.
  Bí mật đúng chuẩn riêng của tổ chức bạn thì phải tự thêm mẫu.</li>
  <li><strong>GC chỉ archive.</strong> File .db không tự nhỏ lại; muốn thu hồi dung lượng phải <code>VACUUM</code> thủ công.</li>
</ul>

<h2><span class="num">07</span> Checklist bóc tách</h2>
<ol class="rules">
  <li>Chép <code>memory.py</code>, đổi <code>DB_PATH</code> về thư mục của bạn.</li>
  <li>Đổi tiền tố biến môi trường cho khớp tên sản phẩm của bạn.</li>
  <li>Sửa <code>CATEGORY_WEIGHTS</code> theo thứ tự giá trị của domain.</li>
  <li>Sửa <code>AUTO_TAG_PATTERNS</code>: thêm domain của bạn, bỏ cái không dùng.</li>
  <li>Thêm mẫu secret riêng vào <code>REDACT_PATTERNS</code>.</li>
  <li>Cắm hai móc: nạp lúc boot (<strong>có trần token</strong>) và lưu lúc kết thúc lượt.</li>
  <li>Chạy đoạn kiểm chứng dưới đây trước khi tin nó.</li>
</ol>

<h2><span class="num">08</span> Kiểm chứng sau khi port</h2>
<p>Đừng tin vì tôi nói vậy — chạy cái này trong project của bạn:</p>
<div class="code-block"><div class="code-head"><span class="file">verify_memory.py</span></div><pre><code>from tools.memory import MemoryDB
import tempfile, pathlib

db = MemoryDB(str(pathlib.Path(tempfile.mkdtemp()) / "t.db"))

a = db.add("dùng jwt với token=abcdefgh12345678 xoay vòng", category="decisions", importance=9)
assert not a["duplicate"] and a["tags"], "add hoặc auto-tag hỏng"
assert db.add("dùng jwt với token=abcdefgh12345678 xoay vòng")["duplicate"], "chống trùng hỏng"
assert "[REDACTED]" in db.memory_get(a["id"])["content"], "redaction hỏng"
assert db.memory_search("jwt")[0]["id"] == a["id"], "tìm kiếm hỏng"

for i in range(6):
    db.add(f"ghi chú vặt {{i}}", category="ingested")
db.gc(max_obs=3)
assert "decisions" in {{m["type"] for m in db.list_all(limit=10)}}, "GC dọn nhầm thứ giá trị cao"
print("memory OK")</code></pre></div>
{callout("tip", "Nếu chỉ lấy một ý từ trang này",
 "Thứ khiến module này dùng được lâu dài không phải BM25 hay RRF — mà là ba thói quen: "
 "<strong>redact trước khi ghi</strong>, <strong>chống trùng ở tầng dữ liệu</strong>, và "
 "<strong>trần token khi nạp</strong>. Ba cái đó áp dụng được cho bất kỳ hệ trí nhớ nào, "
 "kể cả khi bạn tự viết lại từ đầu.")}
'''
