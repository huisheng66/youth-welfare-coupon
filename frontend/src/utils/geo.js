// 地图导航链接（T25 商家详情页）
//
// 商家经纬度存的是高德坐标拾取器输出的 GCJ-02 文本：高德 URI 默认即 GCJ-02，
// 腾讯 URI 默认 coord_type=2（GCJ-02），百度通过 coord_type=gcj02 自动转换。
// 全部为 https 链接：PC 打开网页版地图，移动端可拉起对应 App
// （微信/QQ 内置浏览器拦截 scheme 时自动落到网页版）。
// 无坐标时退化为按地址关键词搜索，保证入口始终可用。
const SRC = 'youth-welfare'

function enc(v) {
  return encodeURIComponent(v ?? '')
}

// 解析整串坐标文本：高德拾取器为 "lng,lat"，腾讯为 "lat,lng"，兼容空格/中文逗号分隔。
// 中国大陆范围内经度 73–136、纬度 3–54，按数值范围自动判别顺序；无法判定返回 null。
export function parseCoordinatePair(text) {
  const m = String(text ?? '').match(/(-?\d{1,3}(?:\.\d{1,8})?)[,，;；\s]+(-?\d{1,3}(?:\.\d{1,8})?)/)
  if (!m) return null
  const a = Number(m[1])
  const b = Number(m[2])
  if (a >= 73 && a <= 136 && b >= 3 && b <= 54) return { longitude: m[1], latitude: m[2] }
  if (b >= 73 && b <= 136 && a >= 3 && a <= 54) return { longitude: m[2], latitude: m[1] }
  return null
}

export function buildNavLinks({ name, address, longitude, latitude }) {
  if (longitude && latitude) {
    const lng = enc(longitude)
    const lat = enc(latitude)
    return [
      {
        label: '高德地图',
        href: `https://uri.amap.com/navigation?to=${lng},${lat},${enc(name)}&mode=car&policy=0&src=${SRC}&callnative=1`,
      },
      {
        label: '腾讯地图',
        href: `https://apis.map.qq.com/uri/v1/routeplan?type=drive&to=${enc(name)}&tocoord=${lat},${lng}&referer=${SRC}`,
      },
      {
        label: '百度地图',
        href: `https://api.map.baidu.com/direction?destination=latlng:${lat},${lng}|name:${enc(name)}&mode=driving&coord_type=gcj02&output=html&src=${SRC}`,
      },
    ]
  }
  if (address) {
    const kw = enc(address)
    return [
      { label: '高德地图搜索', href: `https://uri.amap.com/search?keyword=${kw}&view=map&src=${SRC}` },
      { label: '百度地图搜索', href: `https://api.map.baidu.com/geocoder?address=${kw}&output=html&src=${SRC}` },
    ]
  }
  return []
}
