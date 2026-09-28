import studentBanner from '../assets/images/Bannervlu.avif'
import { HeroQuestionForm } from './HeroQuestionForm'
import { HomeHeader } from './HomeHeader'
import './HomePage.css'

export function HomePage() {
  return (
    <div className="home-page" lang="vi">
      <img
        className="home-hero__image"
        src={studentBanner}
        alt="Sinh viên Đại học Văn Lang trong khuôn viên trường"
      />
      <HomeHeader />

      <main className="home-hero" aria-labelledby="home-heading">
        <div className="home-hero__content">
          <p className="home-hero__eyebrow">TRỢ LÝ CHƯƠNG TRÌNH ĐÀO TẠO &amp; HỌC VỤ</p>
          <h1 id="home-heading">Bạn cần tìm thông tin gì tại Văn Lang?</h1>
          <p className="home-hero__supporting">
            Khám phá chương trình đào tạo, lộ trình học tập và thông tin học vụ tại Trường Đại học Văn Lang.
          </p>
          <HeroQuestionForm />
        </div>
      </main>
    </div>
  )
}
