import './App.css'

function App() {
  return (
    <div className="app-shell" lang="vi">
      <a className="skip-link" href="#question">Đến ô nhập câu hỏi</a>
      <header className="topbar">
        <a className="brand" href="#conversation" aria-label="RAG Chatbot, về cuộc trò chuyện">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M5 5.5h14v10H11l-4.5 3v-3H5z" strokeLinejoin="round" />
              <path d="M8.5 9h7M8.5 12h4" strokeLinecap="round" />
            </svg>
          </span>
          <strong>RAG <span>Chatbot</span></strong>
        </a>
        <span className="header-note">Hỏi đáp cùng kho tri thức</span>
      </header>

      <main className="conversation" id="conversation" aria-labelledby="welcome-heading">
        <section className="welcome">
          <div className="welcome-kicker">
            <span className="welcome-rule" aria-hidden="true" />
            Không gian hỏi đáp
          </div>
          <h1 id="welcome-heading">Bạn đang muốn tìm hiểu điều gì?</h1>
          <p>
            Đặt câu hỏi về kho tri thức đã được chuẩn bị.
            Cùng tìm câu trả lời rõ ràng, có nguồn để đối chiếu.
          </p>
          <div className="context-note">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
              <path d="M3.5 4.5h5l1.5 1 1.5-1h5v11h-5L10 17l-1.5-1.5h-5zM10 5.5V17" strokeLinejoin="round" />
            </svg>
            <span>Nguồn trích dẫn sẽ nằm ngay dưới mỗi câu trả lời.</span>
          </div>
        </section>

        {/* Future assistant messages will include their own inline source cards. */}
        <div className="composer-dock">
          <form className="composer" aria-label="Đặt câu hỏi" onSubmit={(event) => event.preventDefault()}>
            <label htmlFor="question">Câu hỏi của bạn</label>
            <textarea
              id="question"
              name="question"
              rows={2}
              placeholder="Viết điều bạn muốn tìm hiểu…"
              aria-describedby="composer-help"
            />
            <div className="composer-toolbar">
              <span className="composer-context">Dựa trên kho tri thức</span>
              <button type="button" className="send-button" aria-label="Gửi câu hỏi">
                <span>Gửi câu hỏi</span>
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                  <path d="M10 15V5m-4 4 4-4 4 4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          </form>
          <p className="composer-help" id="composer-help">
            Câu trả lời có thể chưa đầy đủ. Hãy đối chiếu với nguồn trích dẫn.
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
