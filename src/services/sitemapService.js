/**
 * Sitemap generation utilities
 */

const xml = require('xml');

const generateSitemap = (baseUrl, entries) => {
  const urls = entries.map(entry => ({
    url: [
      { loc: entry.url },
      { lastmod: entry.lastmod || new Date().toISOString().split('T')[0] },
      { changefreq: entry.changefreq || 'weekly' },
      { priority: entry.priority || '0.8' },
    ],
  }));

  return xml(
    {
      urlset: [
        {
          _attr: {
            xmlns: 'http://www.sitemaps.org/schemas/sitemap/0.9',
          },
        },
        ...urls,
      ],
    },
    true
  );
};

const generateProductSitemap = (baseUrl, products) => {
  const entries = products.map(product => ({
    url: `${baseUrl}/products/${encodeURIComponent(product.slug || product.id)}`,
    lastmod: product.updatedAt
      ? new Date(product.updatedAt).toISOString().split('T')[0]
      : new Date().toISOString().split('T')[0],
    changefreq: 'weekly',
    priority: '0.8',
  }));

  return generateSitemap(baseUrl, entries);
};

const generateCategorySitemap = (baseUrl, categories) => {
  const entries = [
    {
      url: `${baseUrl}/`,
      lastmod: new Date().toISOString().split('T')[0],
      changefreq: 'daily',
      priority: '1.0',
    },
    {
      url: `${baseUrl}/shop`,
      lastmod: new Date().toISOString().split('T')[0],
      changefreq: 'daily',
      priority: '0.9',
    },
    ...categories.map(category => ({
      url: `${baseUrl}/shop?category=${encodeURIComponent(category)}`,
      lastmod: new Date().toISOString().split('T')[0],
      changefreq: 'weekly',
      priority: '0.7',
    })),
  ];

  return generateSitemap(baseUrl, entries);
};

module.exports = {
  generateSitemap,
  generateProductSitemap,
  generateCategorySitemap,
};
