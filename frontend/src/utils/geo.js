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
