import { createRouter, createWebHistory } from 'vue-router'

// Lazy-load views for route-level code splitting (smaller initial kiosk bundle).
const KioskView = () => import('../views/KioskView.vue')
const AdminView = () => import('../views/AdminView.vue')

const routes = [
  { path: '/', name: 'kiosk', component: KioskView, meta: { title: 'Photobooth' } },
  { path: '/admin', name: 'admin', component: AdminView, meta: { title: 'Admin' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `Pixel · ${to.meta.title || 'Photobooth Robot'}`
})

export default router
