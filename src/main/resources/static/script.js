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

    status.innerHTML = '<span class="spinner"></span> Processing your audio...';

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
            status.textContent = "Upload Failed!";
            return;
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        downloadArea.innerHTML = "";

        const a = document.createElement("a");
        a.href = url;
        a.download = "enhanced_audio.wav";
        a.textContent = "⬇ Download Clean Audio";

        downloadArea.appendChild(a);

        status.textContent = "Done!";

    }
    
    catch(error){
        status.textContent = "Server not running!";
        console.error(error);
    }
    uploadBtn.disabled = false;
});