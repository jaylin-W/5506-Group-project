document.addEventListener("DOMContentLoaded", function () {
    const promoCarousel = document.querySelector("#promoCarousel");
    if (promoCarousel && window.bootstrap) {
        new bootstrap.Carousel(promoCarousel, {
            interval: 3200,
            ride: "carousel",
            pause: false,
            touch: true,
            wrap: true,
        });
    }
    console.log("Pill box V2.01 页面已加载");
});
