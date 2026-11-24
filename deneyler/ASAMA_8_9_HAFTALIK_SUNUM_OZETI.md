# Aşama 8 ve Aşama 9 – Haftalık Sunum Özeti (yaklaşık 1 dakika)

Merhaba hocam. Bu hafta iki konuya odaklandım: Aşama 8 ve Aşama 9.

Aşama 8'de, bağlantı arızası durumunda sistemin davranışını ölçtüğüm deneyleri yeniden gözden geçirdim. Dört senaryoyu üçer kez, toplam on iki deney olarak denemiştim: normal ağ, bağlantı kopması, otomatik kurtarma ve failback. Mekanizmanın çalıştığını gördük; Controller arızayı algılayıp alternatif yolu birkaç on milisaniye içinde devreye alıyor. Kullanıcı tarafında ise başarılı denemelerde iki ile beş paketlik kesinti yaşandı. Ancak sonuçlar karışık: on iki deneyin altısı başarısız sayıldı, iki denemede çok yüksek paket kaybı oldu ve topoloji keşfindeki kararsızlık hâlâ açık bir sorun.

Aşama 9'da ise yapay zekâ aşaması için veri toplama altyapısı kurdum. Monitoring Agent'ın ürettiği port ölçümlerini CSV'ye kaydeden ve deneyleri etiketleyen araçlar yazdım. Normal, yük, tıkanıklık ve arıza olmak üzere dört senaryoda toplam 6373 etiketli kayıt topladım. Veri kalitesini kontrol ettim ve 90 otomatik testin tamamı başarıyla geçti.

Dürüst olmak gerekirse, gecikme ve uçtan uca kayıp alanları henüz doldurulmadı, sınıflar dengesiz ve her senaryo tek bir deneyle temsil ediliyor. Yani henüz bir yapay zekâ modeli eğitmedik; bir sonraki adım bu eksikleri tamamlamak.

Teşekkür ederim.
