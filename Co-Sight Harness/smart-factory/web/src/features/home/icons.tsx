/**
 * 首页专属的吉祥物。
 *
 * 通用图标集已经上升到 shared/components/Icon.tsx（首页和智能体创建页共用），
 * 这里只留只属于首页的东西。
 */

/**
 * 趴在输入框右上角的吉祥物：猫耳机甲头，纯装饰。
 *
 * awake = 输入框里有内容：睁眼；空的时候闭眼，并从帽子边上冒 zzz。
 * 睁眼闭眼两套都画出来，靠透明度切换（见 global.css），这样能顺带过渡一下。
 */
export function Mascot({ awake }: { awake: boolean }) {
  return (
    <>
      <svg
        className={`home__mascot${awake ? ' home__mascot--awake' : ''}`}
        viewBox="0 0 96 84"
        fill="none"
        aria-hidden="true"
      >
        {/* 左右耳机 */}
        <rect x="2" y="34" width="14" height="26" rx="7" fill="#dfe4ea" />
        <rect x="80" y="34" width="14" height="26" rx="7" fill="#dfe4ea" />
        {/* 耳朵 */}
        <path d="M26 32L30 8l14 16z" fill="#e9edf2" />
        <path d="M70 32L66 8 52 24z" fill="#e9edf2" />
        {/* 头 */}
        <rect
          x="15"
          y="22"
          width="66"
          height="52"
          rx="20"
          fill="#eef1f5"
          stroke="#dfe4ea"
          strokeWidth="1.5"
        />
        {/* 面罩 */}
        <rect x="23" y="34" width="50" height="24" rx="12" fill="#20242b" />

        {/* 睁眼：两个圆点 */}
        <g className="home__mascot-eyes-open">
          <rect x="34" y="42" width="8" height="8" rx="3" fill="#38e1c8" />
          <rect x="54" y="42" width="8" height="8" rx="3" fill="#38e1c8" />
        </g>

        {/* 闭眼：两道横杠，跟圆点同宽同心 */}
        <g className="home__mascot-eyes-shut">
          <rect x="34" y="44.7" width="8" height="2.6" rx="1.3" fill="#38e1c8" />
          <rect x="54" y="44.7" width="8" height="2.6" rx="1.3" fill="#38e1c8" />
        </g>
      </svg>

      {/* 睡着时从帽子边上冒出来的一串 zzz，三颗错开循环 */}
      {!awake && (
        <span className="home__zzz" aria-hidden="true">
          <span>z</span>
          <span>z</span>
          <span>z</span>
        </span>
      )}
    </>
  );
}
