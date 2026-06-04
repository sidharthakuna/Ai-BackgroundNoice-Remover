const fileInput = document.getElementById("fileInput");
const uploadBtn = document.getElementById("uploadBtn");
const status = document.getElementById("status");
const downloadArea = document.getElementById("downloadArea");
const fileName = document.getElementById("fileName");

// Show selected filename
fileInput.addEventListener("change", () => {
    if(fileInput.files.length > 0){
        fileName.textContent = fileInput.files[0].name;
    }
});

uploadBtn.addEventListener("click", async function(){

    const file = fileInput.files[0];

    if(!file){
        status.textContent = "Please select a file first!";
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    downloadArea.innerHTML = "";

    status.innerHTML =
        '<span class="spinner"></span> Processing your audio...';

    uploadBtn.disabled = true;

    try{

        const response = await fetch(
            "/api/v1/audio/enhance",
            {
                method: "POST",
                body: formData
            }
        );

        if(!response.ok){
            status.textContent =
                `Upload Failed (${response.status})`;
            return;
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        const downloadLink = document.createElement("a");
        downloadLink.href = url;
        downloadLink.download = "enhanced_audio.wav";
        downloadLink.textContent = "⬇ Download Clean Audio";

        downloadArea.appendChild(downloadLink);
        setTimeout(() => {
            URL.revokeObjectURL(url);
        }, 10000);

        status.textContent = "Done!";

    }
    
    catch(error){
        status.textContent =
            "Unable to connect to the server.";
        console.error(error);
    }
    finally{
        uploadBtn.disabled = false;
    }
});