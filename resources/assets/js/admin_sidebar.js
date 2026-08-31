document.addEventListener("DOMContentLoaded", function () {


    const sidebar = document.getElementById("mainSidebar");


    if (!sidebar) {
        console.log("Sidebar not found");
        return;
    }



    const toggleButtons =
        document.querySelectorAll(".sidebar-toggle");



    toggleButtons.forEach(function(button){


        button.addEventListener(
            "click",
            function(){


                sidebar.classList.toggle("closed");


                document.body.classList.toggle(
                    "sidebar-collapsed"
                );



                localStorage.setItem(
                    "sidebarClosed",
                    sidebar.classList.contains("closed")
                );


            }
        );


    });





    // RESTORE LAST STATE

    const saved =
    localStorage.getItem(
        "sidebarClosed"
    );



    if(saved === "true"){


        sidebar.classList.add(
            "closed"
        );


        document.body.classList.add(
            "sidebar-collapsed"
        );


    }



});